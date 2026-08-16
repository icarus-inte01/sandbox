"""국토교통부 아파트 실거래가 수집기.

공공데이터 API ID 15126469를 사용하여 아파트 실거래가 정보를 수집합니다.
분양가 할인율 계산을 위한 시세 기준 데이터로 활용됩니다.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Optional

from src.housing.collectors.base import BaseCollector
from src.housing.models import SaleListing, SupplyType, SaleStatus, TradeRecord

logger = logging.getLogger(__name__)


# 국토부 실거래가 정식 API (15126469 — RTMSDataSvcAptTrade)
# 참고: 개발용 엔드포인트(RTMSDataSvcAptTradeDev)도 존재하나 정식 API 사용
MOLIT_API_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"


class MolitTradeCollector(BaseCollector):
    """국토부 아파트 실거래가 수집기.

    특정 법정동코드 + 계약년월 기준으로 실거래가를 조회합니다.
    XML 응답을 파싱하여 TradeRecord 리스트로 반환합니다.
    """

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.source_name = "molit"

    def collect(self, **kwargs) -> list[SaleListing]:
        """실거래가 collector는 SaleListing을 직접 반환하지 않습니다.
        대신 collect_trades() / get_nearby_prices() 사용.
        """
        logger.warning(
            "MolitTradeCollector.collect() returns empty list. "
            "Use collect_trades() or get_nearby_prices() instead."
        )
        return []

    def collect_trades(
        self,
        lawd_cd: str,
        year_month: str,
        mock: bool = False,
    ) -> list[TradeRecord]:
        """특정 지역+월의 실거래가를 조회합니다.

        Args:
            lawd_cd: 법정동코드 앞 5자리
            year_month: 계약년월 (YYYYMM)
            mock: Mock 모드

        Returns:
            TradeRecord 리스트
        """
        if mock:
            return self._mock_trades(lawd_cd, year_month)

        # numOfRows 상한(1,000) 초과분은 pageNo 루프로 수집
        params = {
            "LAWD_CD": lawd_cd,
            "DEAL_YMD": year_month,
            "pageNo": 1,
            "numOfRows": 1000,
        }
        all_trades: list[TradeRecord] = []
        try:
            while True:
                xml_text = self.client.fetch_text(MOLIT_API_URL, params)
                trades, total_count = self._parse_trades_xml(xml_text, lawd_cd, year_month)
                all_trades.extend(trades)
                # totalCount를 알 수 없거나 마지막 페이지면 종료
                if total_count is None or not trades:
                    break
                if params["pageNo"] * params["numOfRows"] >= total_count:
                    break
                params["pageNo"] += 1
            return all_trades
        except Exception as e:
            logger.error("Failed to fetch trades for %s/%s: %s", lawd_cd, year_month, e)
            return []

    def get_nearby_prices(
        self,
        region_code: str,
        months_back: int = 6,
        area_min: float = 0.0,
        area_max: float = 999.0,
        mock: bool = False,
    ) -> dict[str, Any]:
        """특정 지역의 최근 N개월 실거래가를 집계합니다.

        Args:
            region_code: 법정동코드 앞 5자리
            months_back: 조회할 과거 개월 수
            area_min: 최소 전용면적 (㎡)
            area_max: 최대 전용면적 (㎡)
            mock: Mock 모드

        Returns:
            {
                "avg_price": 평균 거래가 (만원),
                "avg_price_per_area": 면적당 평균가 (만원/㎡),
                "min_price": 최저가,
                "max_price": 최고가,
                "trade_count": 거래 건수,
                "trades": [TradeRecord, ...]
            }
        """
        if mock:
            return self._mock_nearby_prices(region_code)

        all_trades: list[TradeRecord] = []
        today = datetime.now()

        # timedelta(days=30*i)는 월 경계에서 누락/중복 발생 → 달력 월 기준 역산
        year, month = today.year, today.month
        for _ in range(months_back):
            ym = f"{year:04d}{month:02d}"
            trades = self.collect_trades(region_code, ym)
            # 면적 필터링
            for t in trades:
                if area_min <= t.area <= area_max:
                    all_trades.append(t)
            month -= 1
            if month == 0:
                year, month = year - 1, 12

        return self._aggregate_trades(all_trades, region_code)

    def _parse_trades_xml(
        self, xml_text: str, lawd_cd: str, year_month: str
    ) -> tuple[list[TradeRecord], Optional[int]]:
        """XML 응답에서 TradeRecord 리스트와 totalCount를 추출합니다.

        응답 구조: <response><header>..</header><body><items><item>...</item></items><totalCount>N</totalCount></body></response>
        (국토부 실거래가 API는 XML만 반환 — JSON 강제 파싱 시 실패하므로 fetch_text() 사용)
        """
        trades: list[TradeRecord] = []
        total_count: Optional[int] = None
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error("MOLIT XML parse error for %s/%s: %s", lawd_cd, year_month, e)
            return trades, total_count

        header = root.find("header")
        if header is not None:
            result_code = (header.findtext("resultCode") or "").strip()
            if result_code != "00" and result_code != "000":
                logger.warning(
                    "MOLIT API error for %s/%s: code=%s msg=%s",
                    lawd_cd, year_month, result_code, header.findtext("resultMsg"),
                )
                return trades, total_count

        body = root.find("body")
        if body is None:
            return trades, total_count
        tc_text = body.findtext("totalCount")
        if tc_text is not None:
            try:
                total_count = int(tc_text.strip())
            except ValueError:
                total_count = None
        items_container = body.find("items")
        if items_container is None:
            return trades, total_count
        items = items_container.findall("item")
        if not items:
            return trades, total_count

        for item in items:
            try:
                trade = TradeRecord(
                    apartment_name=str(item.findtext("aptNm") or ""),
                    price=self._parse_price(str(item.findtext("dealAmount") or "")),
                    area=float(item.findtext("excluUseAr") or 0),
                    contract_date=f"{year_month}{str(item.findtext('dealDay') or '01'):0>2}",
                    floor=int(item.findtext("floor") or 0),
                    build_year=int(item.findtext("buildYear") or 0),
                    region_code=lawd_cd,
                    region_name=str(item.findtext("umdNm") or ""),
                )
                if trade.price > 0 and trade.area > 0:
                    trades.append(trade)
            except (ValueError, TypeError) as e:
                logger.debug("Skipping invalid trade record: %s", e)
                continue

        return trades, total_count

    def _parse_price(self, price_str: str) -> int:
        """거래금액 문자열을 정수(만원)로 변환합니다.

        "50,000" → 50000, "5억" → 50000
        """
        if not price_str:
            return 0
        cleaned = price_str.replace(",", "").replace(" ", "")
        if "억" in cleaned:
            parts = cleaned.split("억")
            result = int(parts[0]) * 10000
            if len(parts) > 1 and parts[1]:
                result += int(parts[1].replace(",", ""))
            return result
        try:
            return int(cleaned)
        except ValueError:
            return 0

    def _aggregate_trades(
        self, trades: list[TradeRecord], region_code: str
    ) -> dict[str, Any]:
        """실거래가 데이터를 집계합니다."""
        if not trades:
            return {
                "avg_price": 0,
                "avg_price_per_area": 0,
                "min_price": 0,
                "max_price": 0,
                "trade_count": 0,
                "trades": [],
                "region_code": region_code,
            }

        prices = [t.price for t in trades]
        prices_per_area = [t.price / t.area for t in trades if t.area > 0]

        return {
            "avg_price": sum(prices) / len(prices),
            "avg_price_per_area": sum(prices_per_area) / len(prices_per_area) if prices_per_area else 0,
            "min_price": min(prices),
            "max_price": max(prices),
            "trade_count": len(trades),
            "trades": trades,
            "region_code": region_code,
        }

    def _mock_trades(self, lawd_cd: str, year_month: str) -> list[TradeRecord]:
        """Mock 실거래가 데이터"""
        # 지역코드에 따른 Mock 데이터
        mock_by_region = {
            "11110": [  # 서울 종로구
                {"apt": "경희궁자이", "price": 85000, "area": 84.9, "floor": 12, "year": 2022},
                {"apt": "경희궁자이", "price": 82000, "area": 74.8, "floor": 8, "year": 2022},
                {"apt": "돈의문센트레빌", "price": 72000, "area": 84.9, "floor": 15, "year": 2020},
            ],
            "11680": [  # 서울 강남구
                {"apt": "은마아파트", "price": 150000, "area": 84.5, "floor": 5, "year": 1988},
                {"apt": "도곡렉슬", "price": 180000, "area": 84.9, "floor": 18, "year": 2002},
                {"apt": "대치아이파크", "price": 195000, "area": 84.9, "floor": 22, "year": 2006},
            ],
            "41130": [  # 경기 성남시
                {"apt": "판교푸르지오", "price": 98000, "area": 84.9, "floor": 10, "year": 2010},
                {"apt": "판교더샵", "price": 102000, "area": 84.9, "floor": 7, "year": 2012},
            ],
        }

        trades: list[TradeRecord] = []
        for raw_item in mock_by_region.get(lawd_cd, mock_by_region.get("11110", [])):
            trades.append(TradeRecord(
                apartment_name=str(raw_item["apt"]),
                price=int(raw_item["price"]),
                area=float(raw_item["area"]),
                contract_date=f"{year_month}15",
                floor=int(raw_item["floor"]),
                build_year=int(raw_item["year"]),
                region_code=lawd_cd,
                region_name="",
            ))
        return trades

    def _mock_nearby_prices(self, region_code: str) -> dict[str, Any]:
        """Mock 실거래가 집계 데이터."""
        trades = self._mock_trades(region_code, datetime.now().strftime("%Y%m"))
        return self._aggregate_trades(trades, region_code)
