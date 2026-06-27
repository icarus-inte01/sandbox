"""LH 한국토지주택공사 분양/택지 정보 수집기.

공공데이터 API를 통해 LH의 분양임대공고, 공급정보, 용지(입찰) 공고를 수집합니다.

연동 API:
- ID 15058530: 분양임대공고문 조회
- ID 15056765: 분양임대공고별 공급정보
- ID 15072459: 용지(입찰) 공고 내역
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from src.housing.collectors.base import BaseCollector
from src.housing.models import SaleListing, SupplyType, SaleStatus

logger = logging.getLogger(__name__)


# LH API 엔드포인트
# 15058530: 분양임대공고문 조회 (고정 REST — serviceKey만 있으면 사용 가능)
# 15056765: 분양임대공급정보 (고정 REST, 상세 조회용)
# 15072459: 용지공고내역 (파일데이터→odcloud 변환, 계정별 uddi URL 필요)
LH_ANNOUNCE_URL = "http://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
LH_SUPPLY_URL = "http://apis.data.go.kr/B552555/lhLeaseNoticeSplInfo1/getLeaseNoticeSplInfo1"
LH_LAND_URL = "https://api.odcloud.kr/api/15072459/v1/uddi:cfeb195f-6996-426d-99b2-9a2dfa83e2fa"


# 공고유형코드 매핑
ANNOUNCE_TYPE_MAP: dict[str, str] = {
    "01": "분양",
    "02": "임대",
    "03": "혼합",
    "04": "국민임대",
    "05": "행복주택",
    "06": "장기전세",
    "99": "기타",
}


class LHCollector(BaseCollector):
    """LH 분양/택지 정보 수집기."""

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.source_name = "lh"

    def collect_apt(
        self, mock: bool = False
    ) -> list[SaleListing]:
        """LH 아파트 분양공고를 수집합니다.

        분양임대공고문 조회 API (15058530)를 사용합니다.
        """
        if mock:
            return self._mock_collect_apt()

        if not self.client._service_key or self.client._service_key.startswith("${"):
            logger.warning("DATA_GO_KR_API_KEY not configured. Falling back to mock data.")
            return self._mock_collect_apt()

        try:
            items = self._fetch_announce_list(upp_ais_tp_cd="05")
            items += self._fetch_announce_list(upp_ais_tp_cd="13")  # 분양 + 주거복지
            return [self._to_listing(item, "apt") for item in items]
        except Exception as e:
            logger.error("LH announce API call failed: %s", e)
            return self._mock_collect_apt()

    def _fetch_announce_list(self, upp_ais_tp_cd: str = "05") -> list[dict[str, Any]]:
        """LH 분양임대공고문 API를 호출하여 목록을 반환합니다.

        Args:
            upp_ais_tp_cd: 공고유형코드 (05=분양주택, 06=임대주택, 13=주거복지)
        """
        params: dict[str, Any] = {
            "pageNo": 1,
            "numOfRows": 100,
            "UPP_AIS_TP_CD": upp_ais_tp_cd,
            "type": "json",
        }
        resp = self.client.fetch(LH_ANNOUNCE_URL, params)
        # apis.data.go.kr 응답은 배열일 수도 있고 표준 response>body 구조일 수도 있음
        if isinstance(resp, list):
            if resp:
                logger.info("LH API list response — first item keys: %s", list(resp[0].keys()))
            return resp
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
            logger.info("LH API standard response — first item keys: %s", list(item_list[0].keys()))
            logger.info("LH API first item sample: %s", str(item_list[0])[:500])
        return item_list

    def collect_land(
        self, mock: bool = False
    ) -> list[SaleListing]:
        """LH 택지/용지 공고를 수집합니다.

        용지(입찰) 공고 내역 API (15072459)를 사용합니다.
        15072459는 계정별 uddi URL이 필요 — LH_LAND_URL이 설정될 때까지 mock 사용.
        """
        if mock or LH_LAND_URL is None:
            return self._mock_collect_land()

        if not self.client._service_key or self.client._service_key.startswith("${"):
            logger.warning("DATA_GO_KR_API_KEY not configured. Falling back to mock data.")
            return self._mock_collect_land()

        try:
            params: dict[str, Any] = {"page": 1, "perPage": 100}
            resp = self.client.fetch(LH_LAND_URL, params)
            data = self.client._extract_data(resp)
            if data:
                logger.info("LH land API — first item keys: %s", list(data[0].keys()))
                logger.info("LH land API first item sample: %s", str(data[0])[:500])
            result = [self._to_listing(item, "land") for item in data]
            if result:
                logger.info("LH land collect — first listing: name=%r region=%r price=%r units=%r date=%r",
                            result[0].name, result[0].region, result[0].price,
                            result[0].units, result[0].announcement_date)
                logger.info("LH land collect — total %d items, 5 names: %s",
                            len(result), [r.name for r in result[:5]])
            return result
        except Exception as e:
            logger.error("LH land API call failed: %s", e)
            return self._mock_collect_land()

    def collect(self, **kwargs) -> list[SaleListing]:
        """전체 LH 데이터 수집 (분양 + 택지)."""
        mock = kwargs.get("mock", False)
        results = []
        results.extend(self.collect_apt(mock=mock))
        results.extend(self.collect_land(mock=mock))
        if results:
            logger.info("LH collect — first item: name=%r region=%r price=%r units=%r source=%s",
                        results[0].name, results[0].region, results[0].price,
                        results[0].units, results[0].source)
            logger.info("LH collect — total %d items, sample of 3 names: %s",
                        len(results), [r.name for r in results[:3]])
        return results

    def _mock_collect_apt(self) -> list[SaleListing]:
        """Mock LH 분양 데이터."""
        mock_data = [
            {
                "pblanc_no": "LH2026001",
                "pblanc_nm": "LH 행복주택 의정부 민락",
                "region": "경기도 의정부시",
                "announce_type": "행복주택",
                "total_units": 480,
                "supply_price": 22000,
                "announce_date": "2026-07-01",
                "builder": "LH",
            },
            {
                "pblanc_no": "LH2026002",
                "pblanc_nm": "LH 천안 성성 공공분양",
                "region": "충청남도 천안시",
                "announce_type": "분양",
                "total_units": 620,
                "supply_price": 28000,
                "announce_date": "2026-06-15",
                "builder": "LH",
            },
            {
                "pblanc_no": "LH2026003",
                "pblanc_nm": "LH 부산 정관 공공분양",
                "region": "부산광역시 기장군",
                "announce_type": "분양",
                "total_units": 350,
                "supply_price": 25000,
                "announce_date": "2026-07-20",
                "builder": "LH",
            },
            {
                "pblanc_no": "LH2026004",
                "pblanc_nm": "LH 인천 검단 행복주택",
                "region": "인천광역시 서구",
                "announce_type": "행복주택",
                "total_units": 720,
                "supply_price": 19000,
                "announce_date": "2026-08-01",
                "builder": "LH",
            },
            {
                "pblanc_no": "LH2026005",
                "pblanc_nm": "LH 대전 노은 공공분양",
                "region": "대전광역시 유성구",
                "announce_type": "분양",
                "total_units": 280,
                "supply_price": 30000,
                "announce_date": "2026-05-30",
                "builder": "LH",
            },
        ]
        return [self._to_listing(item, "apt") for item in mock_data]

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

        세 가지 입력 형식을 처리:
        - LH 분양임대공고문 API: PAN_NM, CNP_CD_NM, PAN_NT_ST_DT 등
        - LH 용지공고 API (15072459): 공고명, 매물위치, 공고게시일 등 (한글 키)
        - Mock 데이터: pblanc_nm, region, announce_date 등
        """
        name = (
            item.get("PAN_NM") or item.get("공고명")
            or item.get("pblanc_nm") or "알 수 없음"
        )
        region = (
            item.get("CNP_CD_NM") or item.get("매물위치")
            or item.get("사업지구") or item.get("region", "")
        )
        announce_date = (
            item.get("PAN_NT_ST_DT") or item.get("공고게시일")
            or item.get("announce_date", "")
        )
        if announce_date and "." in announce_date:
            announce_date = announce_date.replace(".", "-")

        if category == "land":
            supply_type = SupplyType.LAND
        else:
            atype = item.get("UPP_AIS_TP_CD_NM") or item.get("announce_type", "")
            if "행복" in atype:
                supply_type = SupplyType.PUBLIC
            else:
                supply_type = SupplyType.APT

        units = int(item.get("total_units", 0) or 0)
        price = int(
            item.get("공급예정금액") or item.get("supply_price", 0) or 0
        )
        builder = item.get("builder", "LH")

        return SaleListing(
            name=name,
            region=region,
            supply_type=supply_type,
            status=SaleStatus.PLANNED,
            units=units,
            price=price,
            builder=builder,
            announcement_date=announce_date,
            source="lh",
        )
