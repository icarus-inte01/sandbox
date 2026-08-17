"""토지 매매 실거래가 수집기.

국토교통부_토지 매매 실거래가 자료 API를 사용하여
토지 실거래가 데이터를 수집합니다.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Optional

from src.housing.collectors.base import BaseCollector
from src.housing.utils.api_client import OdcloudClient

logger = logging.getLogger(__name__)

# 토지 매매 실거래가 API
API_BASE = "https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade"
API_URL = f"{API_BASE}/getRTMSDataSvcLandTrade"


class LandTradeCollector(BaseCollector):
    """토지 매매 실거래가 수집기."""

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.source_name = "land_trade"
        self.client = OdcloudClient(config)

    def collect(
        self,
        pnu: str,
        year: Optional[int] = None,
        months: int = 6,
    ) -> Optional[dict[str, Any]]:
        """토지 실거래가를 조회합니다.

        Args:
            pnu: PNU 코드 (19자리 또는 10자리)
            years: 조회할 과거 개월 수 (기본 6개월)

        Returns:
            거래 정보 딕셔너리 또는 None
        """
        if not self.client._service_key or self.client._service_key.startswith("${"):
            logger.warning("DATA_GO_KR_API_KEY not configured for land trade")
            return None

        # PNU → LAWD_CD 변환 (앞 5자리)
        lawd_cd = self._pnu_to_lawd_cd(pnu)
        if not lawd_cd:
            logger.warning("Invalid PNU for LAWD_CD conversion: %s", pnu)
            return None

        # 최근 N개월 데이터 조회
        today = datetime.now()
        if year is None:
            year = today.year

        trades = []
        for i in range(months):
            # 월 계산 (년도 넘김 처리)
            month = today.month - i
            target_year = year
            while month <= 0:
                month += 12
                target_year -= 1

            deal_ymd = f"{target_year}{month:02d}"

            try:
                xml_text = self.client.fetch_text(API_URL, {
                    "LAWD_CD": lawd_cd,
                    "DEAL_YMD": deal_ymd,
                })

                items = self._parse_xml_response(xml_text)
                if items:
                    trades.extend(items)
                    logger.debug(
                        "Land trade fetched: LAWD_CD=%s, DEAL_YMD=%s, %d items",
                        lawd_cd, deal_ymd, len(items),
                    )
            except Exception as e:
                logger.debug(
                    "Land trade fetch failed: LAWD_CD=%s, DEAL_YMD=%s: %s",
                    lawd_cd, deal_ymd, e,
                )

        if not trades:
            return None

        # 거래 데이터 집계
        return self._aggregate_trades(trades, pnu)

    def _pnu_to_lawd_cd(self, pnu: str) -> Optional[str]:
        """PNU를 LAWD_CD(5자리 지역코드)로 변환합니다.

        PNU 형식: 시도(2) + 시군구(3) + 읍면동(3) + 리(2) + 산(1) + 본번(4) + 부번(4)
        LAWD_CD = PNU 앞 5자리 (시도 + 시군구)
        """
        if not pnu or len(pnu) < 5:
            return None
        return pnu[:5]

    def _parse_xml_response(self, xml_text: str) -> list[dict[str, Any]]:
        """XML 응답을 파싱하여 거래 리스트를 반환합니다."""
        try:
            root = ET.fromstring(xml_text)
            items = []

            for item_elem in root.findall(".//item"):
                item = {}
                for child in item_elem:
                    item[child.tag] = child.text.strip() if child.text else ""
                items.append(item)

            return items
        except ET.ParseError as e:
            logger.debug("XML parse error: %s", e)
            return []

    def _aggregate_trades(
        self, trades: list[dict[str, Any]], pnu: str
    ) -> Optional[dict[str, Any]]:
        """거래 데이터를 집계합니다.

        같은 시군구의 최근 거래들을 모아 평균 거래가를 계산합니다.
        """
        sgg_cd = pnu[:5]
        if not sgg_cd:
            return None

        matched = []
        for trade in trades:
            trade_sgg = trade.get("sggCd", "")
            if trade_sgg and trade_sgg == sgg_cd:
                try:
                    price_str = trade.get("dealAmount", "0")
                    price = int(price_str.replace(",", ""))
                    area_str = trade.get("dealArea", "0")
                    area = float(area_str.replace(",", ""))

                    if price > 0 and area > 0:
                        year = trade.get("dealYear", "")
                        month = trade.get("dealMonth", "")
                        day = trade.get("dealDay", "")
                        matched.append({
                            "price_manwon": price,
                            "area_m2": area,
                            "price_per_m2": round(price / area, 2),
                            "date": f"{year}-{month}-{day}",
                        })
                except (ValueError, TypeError):
                    continue

        if not matched:
            return None

        avg_price_per_m2 = sum(t["price_per_m2"] for t in matched) / len(matched)
        latest = max(matched, key=lambda x: x["date"])

        return {
            "source": "land_trade",
            "trade_count": len(matched),
            "avg_price_per_m2": round(avg_price_per_m2, 0),
            "latest_trade": latest,
            "pnu": pnu,
        }


