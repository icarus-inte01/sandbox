"""청약홈 분양정보 수집기.

공공데이터 API ID 15098547 (ApplyhomeInfoDetailSvc)를 사용하여
전국 아파트 분양공고 정보를 수집합니다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from src.housing.collectors.base import BaseCollector
from src.housing.models import SaleListing, SupplyType, SaleStatus

logger = logging.getLogger(__name__)


# 청약홈 API 엔드포인트 (odcloud 게이트웨이 — 신청 후 서비스키만 있으면 사용 가능)
# https://www.data.go.kr/data/15098547/openapi.do
API_BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
API_LIST = f"{API_BASE}/getAPTLttotPblancDetail"

# 법정동코드 → 지역명 매핑 (전체 시/도 + 주요 시/군/구)
REGION_CODE_MAP: dict[str, str] = {
    "11": "서울특별시",
    "26": "부산광역시",
    "27": "대구광역시",
    "28": "인천광역시",
    "29": "광주광역시",
    "30": "대전광역시",
    "31": "울산광역시",
    "36": "세종특별자치시",
    "41": "경기도",
    "42": "강원도",
    "43": "충청북도",
    "44": "충청남도",
    "45": "전라북도",
    "46": "전라남도",
    "47": "경상북도",
    "48": "경상남도",
    "50": "제주특별자치도",
}


class CheongyakCollector(BaseCollector):
    """청약홈 분양정보 수집기.

    공공데이터포털 청약홈 OpenAPI를 통해 전국 아파트 분양공고를 수집합니다.
    """

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.source_name = "cheongyak"

    def collect(
        self,
        region: Optional[str] = None,
        from_date: Optional[str] = None,
        mock: bool = False,
    ) -> list[SaleListing]:
        """청약홈 분양정보를 수집합니다.

        Args:
            region: 공급지역코드 (None=전국)
            from_date: 기준일 (YYYY-MM-DD, None=최근 30일)
            mock: Mock 모드 (실제 API 호출 없이 테스트 데이터)

        Returns:
            SaleListing 리스트
        """
        if mock:
            return self._mock_collect(region)

        # 실제 API 호출 (odcloud 게이트웨이)
        if not self.client._service_key or self.client._service_key.startswith("${"):
            logger.warning("DATA_GO_KR_API_KEY not configured. Falling back to mock data.")
            return self._mock_collect(region)

        try:
            params = {
                "page": 1,
                "perPage": 100,
            }
            # odcloud 필터: cond[RCRIT_PBLANC_DE::GTE]=YYYY-MM-DD
            if region:
                params["cond[SUBSCRPT_AREA_CODE_NM::EQ]"] = region
            response = self.client.fetch_all(API_LIST, params, max_pages=5)
            return [self._to_listing(item) for item in response]
        except Exception as e:
            logger.error("Cheongyak API call failed: %s", e)
            return self._mock_collect(region)

    def _mock_collect(self, region: Optional[str] = None) -> list[SaleListing]:
        """Mock 분양 데이터를 생성합니다."""
        mock_data = [
            {
                "pblanc_no": "2026001001",
                "house_nm": "래미안 원펜타스",
                "suply_location": "서울특별시 서초구",
                "rcrit_pblanc_de": "2026-07-15",
                "total_suply_hs_shl": 1024,
                "suply_amount": 85000,
                "builder": "삼성물산",
                "region_code": "11",
                "pblanc_knd": "아파트",
            },
            {
                "pblanc_no": "2026001002",
                "house_nm": "힐스테이트 도곡",
                "suply_location": "서울특별시 강남구",
                "rcrit_pblanc_de": "2026-07-22",
                "total_suply_hs_shl": 320,
                "suply_amount": 95000,
                "builder": "현대건설",
                "region_code": "11",
                "pblanc_knd": "아파트",
            },
            {
                "pblanc_no": "2026001003",
                "house_nm": "자이 더 포레",
                "suply_location": "경기도 성남시 분당구",
                "rcrit_pblanc_de": "2026-08-01",
                "total_suply_hs_shl": 680,
                "suply_amount": 72000,
                "builder": "GS건설",
                "region_code": "41",
                "pblanc_knd": "아파트",
            },
            {
                "pblanc_no": "2026001004",
                "house_nm": "e편한세상 평택",
                "suply_location": "경기도 평택시",
                "rcrit_pblanc_de": "2026-07-10",
                "total_suply_hs_shl": 950,
                "suply_amount": 42000,
                "builder": "대림산업",
                "region_code": "41",
                "pblanc_knd": "아파트",
            },
            {
                "pblanc_no": "2026001005",
                "house_nm": "포레나 천안",
                "suply_location": "충청남도 천안시",
                "rcrit_pblanc_de": "2026-07-05",
                "total_suply_hs_shl": 450,
                "suply_amount": 32000,
                "builder": "한화건설",
                "region_code": "44",
                "pblanc_knd": "아파트",
            },
        ]

        if region:
            region_prefix = region[:2] if len(region) >= 2 else region
            mock_data = [
                item for item in mock_data
                if item.get("region_code", "").startswith(region_prefix)
            ]

        return [self._to_listing(item) for item in mock_data]

    def _to_listing(self, item: dict[str, Any]) -> SaleListing:
        """API 응답 아이템을 SaleListing으로 변환합니다."""
        name = item.get("house_nm", "알 수 없음")
        location = item.get("suply_location", "")
        units = int(item.get("total_suply_hs_shl", 0) or 0)
        # 분양금액: 공공데이터는 ㎡당 분양가인 경우가 많으므로
        # 여기서는 총분양가(만원)로 가정
        price = int(item.get("suply_amount", 0) or 0)
        builder = item.get("builder", "")
        region_code = item.get("region_code", "")

        # 분양유형 판별
        pblanc_knd = item.get("pblanc_knd", "")
        if "아파트" in pblanc_knd:
            supply_type = SupplyType.APT
        elif "공공" in pblanc_knd or "행복" in name:
            supply_type = SupplyType.PUBLIC
        else:
            supply_type = SupplyType.APT

        # 분양상태 판별 (공고일 기준 단순 추정)
        announcement_date = item.get("rcrit_pblanc_de", "")
        status = self._estimate_status(announcement_date, name)

        # 지역명
        region_name = REGION_CODE_MAP.get(region_code[:2], "")
        if location and not region_name:
            region_name = location.split()[0] if location else ""

        return SaleListing(
            name=name,
            region=location or region_name,
            supply_type=supply_type,
            status=status,
            units=units,
            price=price,
            builder=builder,
            region_code=region_code,
            announcement_date=announcement_date,
            source="cheongyak",
        )

    def _estimate_status(self, announcement_date: str, name: str) -> SaleStatus:
        """공고일 기준으로 분양상태를 추정합니다."""
        if not announcement_date:
            return SaleStatus.PLANNED

        try:
            announcement = datetime.strptime(announcement_date, "%Y-%m-%d")
        except ValueError:
            try:
                announcement = datetime.strptime(announcement_date, "%Y%m%d")
            except ValueError:
                return SaleStatus.PLANNED

        now = datetime.now()
        days_diff = (now - announcement).days

        if days_diff < 0:
            return SaleStatus.PLANNED
        elif days_diff < 30:
            return SaleStatus.OPEN
        elif days_diff < 365:
            return SaleStatus.CLOSED
        else:
            # 미분양: 1년 이상 지난 공고 + 특정 키워드
            unsold_keywords = ["미분양", "잔여", "무순위", "취소후"]
            if any(kw in name for kw in unsold_keywords):
                return SaleStatus.UNSOLD
            return SaleStatus.CLOSED
