"""LH 한국토지주택공사 토지/용지 정보 수집기.

공공데이터 API를 통해 LH의 토지(용지) 공고를 수집합니다.
분양주택/주거복지 공고는 cheongyak으로 대체되므로 수집하지 않습니다.

연동 API:
- ID 15058530: 분양임대공고문 조회 (upp_ais_tp_cd=01 토지만 수집)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from src.housing.collectors.base import BaseCollector
from src.housing.models import SaleListing, SupplyType, SaleStatus

logger = logging.getLogger(__name__)


LH_ANNOUNCE_URL = "http://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"

PAN_SS_STATUS_MAP: dict[str, SaleStatus] = {
    "공고중": SaleStatus.OPEN,
    "접수중": SaleStatus.OPEN,
    "접수마감": SaleStatus.CLOSED,
    "상담요청": SaleStatus.UNSOLD,
}

_SUPPLY_PURPOSE_KEYWORDS: dict[str, str] = {
    "점포겸용": "점포겸용",
    "준주거": "준주거",
    "주상복합": "주상복합",
    "근린생활시설": "근린생활시설",
    "상업업무": "상업업무",
    "상업시설": "상업시설",
    "업무시설": "업무시설",
    "주상": "주상복합",
    "주거": "주거",
    "상업": "상업",
    "공동주택": "공동주택",
    "단독주택": "단독주택",
}


class LHCollector(BaseCollector):
    """LH 분양/택지 정보 수집기."""

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.source_name = "lh"

    def _fetch_announce_list(self, upp_ais_tp_cd: str = "01") -> list[dict[str, Any]]:
        """15058530 API를 호출하여 공고 목록을 반환합니다."""
        params: dict[str, Any] = {
            "PAGE": 1,
            "PG_SZ": 500,
            "UPP_AIS_TP_CD": upp_ais_tp_cd,
            "type": "json",
        }
        resp = self.client.fetch(LH_ANNOUNCE_URL, params)

        # LH REST API는 [{"dsSch": [...]}, {"dsList": [...], "resHeader": [...]}] 구조로 응답
        if isinstance(resp, list):
            for elem in resp:
                if isinstance(elem, dict) and "dsList" in elem:
                    items = elem["dsList"]
                    if items:
                        logger.info("LH dsList — %d items for code %s", len(items), upp_ais_tp_cd)
                    return items
            logger.info("LH API — no dsList found for code %s", upp_ais_tp_cd)
            return []

        if isinstance(resp, dict) and "dsSch" in resp:
            items = resp["dsSch"]
            if items:
                logger.info("LH dsSch format (dict) — %d items for code %s", len(items), upp_ais_tp_cd)
            return items

        header = resp.get("response", {}).get("header", {})
        if header.get("resultCode") != "00":
            logger.warning("LH API error (%s): %s %s", upp_ais_tp_cd,
                           header.get("resultCode"), header.get("resultMsg"))
            return []
        body = resp.get("response", {}).get("body", {})
        items = body.get("items", {})
        item_list = items.get("item", [])
        if isinstance(item_list, dict):
            item_list = [item_list]
        if item_list:
            logger.info("LH API standard response — %d items for code %s", len(item_list), upp_ais_tp_cd)
        return item_list

    def collect_land(
        self, mock: bool = False
    ) -> list[SaleListing]:
        """LH 택지/용지 공고를 수집합니다.

        15058530 분양임대공고문 조회 API에서 용지 (UPP_AIS_TP_CD=01)를 가져옵니다.
        15072459(ODCloud)는 15058530으로 대체되었습니다.
        """
        if mock:
            return self._mock_collect_land()

        if not self.client._service_key or self.client._service_key.startswith("${"):
            logger.warning("DATA_GO_KR_API_KEY not configured. Falling back to mock data.")
            return self._mock_collect_land()

        try:
            items = self._fetch_announce_list(upp_ais_tp_cd="01")
            results = []
            for item in items:
                listing = self._to_listing(item, "land")
                if listing.status != SaleStatus.CLOSED:
                    results.append(listing)
            logger.info("LH land — total %d, CLOSED 제외 %d개",
                        len(items), len(items) - len(results))
            return results
        except Exception as e:
            logger.error("LH land API call failed: %s", e)
            return self._mock_collect_land()

    def collect(self, **kwargs) -> list[SaleListing]:
        """LH 토지/용지 데이터 수집."""
        mock = kwargs.get("mock", False)
        results = self.collect_land(mock=mock)
        if results:
            logger.info("LH collect — total %d items, sample of 3 names: %s",
                        len(results), [r.name for r in results[:3]])
        return results

    def _mock_collect_land(self) -> list[SaleListing]:
        """Mock LH 택지 데이터."""
        mock_data = [
            {
                "pblanc_no": "LHL2026001",
                "pblanc_nm": "LH 평택 고덕 택지",
                "region": "경기도 평택시",
                "announce_type": "택지",
                "total_units": 150,
                "supply_price": 15000,
                "announce_date": "2026-07-10",
                "builder": "LH",
            },
            {
                "pblanc_no": "LHL2026002",
                "pblanc_nm": "LH 세종 6생활권 택지",
                "region": "세종특별자치시",
                "announce_type": "택지",
                "total_units": 200,
                "supply_price": 18000,
                "announce_date": "2026-06-20",
                "builder": "LH",
            },
            {
                "pblanc_no": "LHL2026003",
                "pblanc_nm": "LH 아산 탕정 택지",
                "region": "충청남도 아산시",
                "announce_type": "택지",
                "total_units": 120,
                "supply_price": 12000,
                "announce_date": "2026-08-05",
                "builder": "LH",
            },
        ]
        return [self._to_listing(item, "land") for item in mock_data]

    def _to_listing(self, item: dict[str, Any], category: str) -> SaleListing:
        """API 응답을 SaleListing으로 변환.

        네 가지 입력 형식을 처리:
        - LH dsSch/표준 응답: pan_nm, cnp_cd_nm, pan_dt 등 (소문자 snake_case)
        - LH 용지공고 API (15072459): 공고명, 매물위치, 공고게시일 등 (한글 키)
        - 구형 표준 응답: PAN_NM, CNP_CD_NM 등 (대문자)
        - Mock 데이터: pblanc_nm, region, announce_date 등
        """
        name = (
            item.get("pan_nm") or item.get("PAN_NM") or item.get("공고명")
            or item.get("pblanc_nm") or "알 수 없음"
        )
        region = (
            item.get("cnp_cd_nm") or item.get("CNP_CD_NM") or item.get("매물위치")
            or item.get("사업지구") or item.get("region", "")
        )
        announce_date = (
            item.get("pan_dt") or item.get("pan_nt_st_dt")
            or item.get("PAN_NT_ST_DT") or item.get("공고게시일")
            or item.get("announce_date", "")
        )
        if announce_date and "." in announce_date:
            announce_date = announce_date.replace(".", "-")

        if category == "land":
            supply_type = SupplyType.LAND
        else:
            atype = (
                item.get("ais_tp_cd_nm") or item.get("AIS_TP_CD_NM")
                or item.get("UPP_AIS_TP_CD_NM") or item.get("announce_type", "")
            )
            if "행복" in atype:
                supply_type = SupplyType.PUBLIC
            else:
                supply_type = SupplyType.APT

        pan_ss = item.get("pan_ss") or item.get("PAN_SS", "")
        status = PAN_SS_STATUS_MAP.get(pan_ss, SaleStatus.PLANNED)

        units = int(item.get("total_units", 0) or 0)
        raw_price = (
            item.get("공급예정금액") or item.get("SPL_XPC_AMT")
            or item.get("supply_price", 0) or 0
        )
        if isinstance(raw_price, str) and raw_price.isdigit():
            price = int(raw_price)
            if price > 100_000_000:
                price //= 10000
        else:
            price = int(raw_price)
        builder = item.get("builder", "LH")

        pan_nm = name
        supply_purpose = ""
        for kw, label in _SUPPLY_PURPOSE_KEYWORDS.items():
            if kw in pan_nm:
                supply_purpose = label
                break

        dtl_url = item.get("dtl_url") or item.get("DTL_URL", "")
        if not dtl_url:
            pan_id = item.get("pan_id") or item.get("PAN_ID", "")
            if pan_id:
                dtl_url = f"https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?panId={pan_id}"

        return SaleListing(
            name=name,
            region=region,
            supply_type=supply_type,
            status=status,
            units=units,
            price=price,
            supply_purpose=supply_purpose,
            builder=builder,
            announcement_date=announce_date,
            raw_data={"dtl_url": dtl_url},
            source="lh",
        )
