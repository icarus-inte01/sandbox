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


API_BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
API_LIST = f"{API_BASE}/getAPTLttotPblancDetail"
API_MDL = f"{API_BASE}/getAPTLttotPblancMdl"

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


def _sum_households(model: dict[str, Any]) -> int:
    return (
        int(model.get("SUPLY_HSHLDCO", 0) or 0)
        + int(model.get("SPSPLY_HSHLDCO", 0) or 0)
        + int(model.get("ETC_HSHLDCO", 0) or 0)
        + int(model.get("NWWDS_HSHLDCO", 0) or 0)
        + int(model.get("NWBB_HSHLDCO", 0) or 0)
    )


class CheongyakCollector(BaseCollector):
    """청약홈 분양정보 수집기."""

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.source_name = "cheongyak"

    def collect(
        self,
        region: Optional[str] = None,
        from_date: Optional[str] = None,
        mock: bool = False,
    ) -> list[SaleListing]:
        """청약홈 분양정보를 수집합니다."""
        if mock:
            return self._mock_collect(region)

        if not self.client._service_key or self.client._service_key.startswith("${"):
            logger.warning("DATA_GO_KR_API_KEY not configured. Falling back to mock data.")
            return self._mock_collect(region)

        try:
            now = datetime.now()
            cutoff = (now - timedelta(days=365)).strftime("%Y-%m-%d")

            params = {"page": 1, "perPage": 100}
            # 365일 이내 공고를 가져와서 상태 분류:
            #   0-30일 → OPEN, 31-364일 → CLOSED, 365일+키워드매칭 → UNSOLD
            # 이전 90일 컷오프는 UNSOLD(잔여/미분양/취소분)를 API 단에서 차단하여 누락시킴
            params["cond[RCRIT_PBLANC_DE::GTE]"] = cutoff
            if region:
                params["cond[SUBSCRPT_AREA_CODE_NM::EQ]"] = region

            detail_items = self.client.fetch_all(API_LIST, params, max_pages=5)

            # detail Items의 house_manage_no만 model에서 조회
            target_keys = {item.get("HOUSE_MANAGE_NO", "") for item in detail_items if item.get("HOUSE_MANAGE_NO")}

            model_items: list[dict] = []
            if target_keys:
                model_params = {"page": 1, "perPage": 100}
                try:
                    found_keys: set[str] = set()
                    for page in range(1, 31):
                        model_params["page"] = page
                        result = self.client.fetch(API_MDL, dict(model_params))
                        data = result.get("data", [])
                        if not data:
                            break
                        model_items.extend(data)
                        for m in data:
                            k = m.get("HOUSE_MANAGE_NO", "")
                            if k in target_keys:
                                found_keys.add(k)
                        if found_keys == target_keys:
                            logger.info("Model detail 커버: %d개 단지, page %d에서 완료", len(target_keys), page)
                            break
                except Exception:
                    logger.warning("Model endpoint failed, proceeding without price data.")
                    model_items = []

            models_by_house: dict[str, list[dict]] = {}
            for m in model_items:
                key = m.get("HOUSE_MANAGE_NO", "")
                if key:
                    models_by_house.setdefault(key, []).append(m)

            result: list[SaleListing] = []
            for item in detail_items:
                listing = self._to_listing(item)
                key = item.get("HOUSE_MANAGE_NO", "")
                models = models_by_house.get(key, [])
                if models:
                    listing.units_info = [
                        {
                            "model_no": m.get("MODEL_NO", ""),
                            "house_type": m.get("HOUSE_TY", ""),
                            "supply_area": m.get("SUPLY_AR", ""),
                            "price": int(m.get("LTTOT_TOP_AMOUNT", 0) or 0),
                            "households": _sum_households(m),
                        }
                        for m in models
                    ]
                    # 평당분양가 계산 (price는 만원, supply_area는 m²)
                    for u in listing.units_info:
                        area = u.get("supply_area")
                        if area:
                            try:
                                a = float(area)
                                if a > 0:
                                    u["price_per_m2"] = round(u["price"] / a, 0)
                                    u["price_per_pyung"] = round(u["price"] / a * 3.3058, 0)
                            except (ValueError, TypeError):
                                pass
                    prices = [u["price"] for u in listing.units_info if u["price"] > 0]
                    if prices:
                        listing.price = min(prices)
                result.append(listing)
            return result
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
                "units_info": [
                    {"model_no": "1", "house_type": "전용 59", "supply_area": "59.0", "price": 78000, "households": 512},
                    {"model_no": "2", "house_type": "전용 84", "supply_area": "84.0", "price": 95000, "households": 384},
                    {"model_no": "3", "house_type": "전용 112", "supply_area": "112.0", "price": 118000, "households": 128},
                ],
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
                "units_info": [
                    {"model_no": "1", "house_type": "전용 59", "supply_area": "59.0", "price": 82000, "households": 160},
                    {"model_no": "2", "house_type": "전용 84", "supply_area": "84.0", "price": 105000, "households": 160},
                ],
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
                "units_info": [
                    {"model_no": "1", "house_type": "전용 59", "supply_area": "59.0", "price": 65000, "households": 340},
                    {"model_no": "2", "house_type": "전용 84", "supply_area": "84.0", "price": 78000, "households": 340},
                ],
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
                "units_info": [
                    {"model_no": "1", "house_type": "전용 59", "supply_area": "59.0", "price": 38000, "households": 475},
                    {"model_no": "2", "house_type": "전용 84", "supply_area": "84.0", "price": 45000, "households": 380},
                    {"model_no": "3", "house_type": "전용 112", "supply_area": "112.0", "price": 55000, "households": 95},
                ],
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
                "units_info": [
                    {"model_no": "1", "house_type": "전용 59", "supply_area": "59.0", "price": 28000, "households": 270},
                    {"model_no": "2", "house_type": "전용 84", "supply_area": "84.0", "price": 35000, "households": 180},
                ],
            },
            # UNSOLD 시나리오: 잔여세대 (예: 군산 세경아파트)
            {
                "pblanc_no": "2025004001",
                "house_nm": "군산 세경아파트 우선분양전환 후 잔여세대",
                "suply_location": "전라북도 군산시",
                "rcrit_pblanc_de": "2025-04-15",
                "total_suply_hs_shl": 120,
                "suply_amount": 18000,
                "builder": "세경종합건설",
                "region_code": "45",
                "pblanc_knd": "아파트",
                "units_info": [
                    {"model_no": "1", "house_type": "전용 59", "supply_area": "59.0", "price": 16500, "households": 70},
                    {"model_no": "2", "house_type": "전용 84", "supply_area": "84.0", "price": 19500, "households": 50},
                ],
            },
            # UNSOLD 시나리오: 조합원 취소분 (예: 상무 양우내안에 퍼스트힐)
            {
                "pblanc_no": "2025002003",
                "house_nm": "상무 양우내안에 퍼스트힐(조합원 취소분)",
                "suply_location": "광주광역시 서구",
                "rcrit_pblanc_de": "2025-03-01",
                "total_suply_hs_shl": 85,
                "suply_amount": 28000,
                "builder": "양우건설",
                "region_code": "50",
                "pblanc_knd": "아파트",
                "units_info": [
                    {"model_no": "1", "house_type": "전용 59", "supply_area": "59.0", "price": 25500, "households": 50},
                    {"model_no": "2", "house_type": "전용 84", "supply_area": "84.0", "price": 31000, "households": 35},
                ],
            },
            # UNSOLD 시나리오: 보류지 (예: 북서울자이 폴라리스)
            {
                "pblanc_no": "2025003010",
                "house_nm": "북서울자이 폴라리스(보류지)",
                "suply_location": "서울특별시 노원구",
                "rcrit_pblanc_de": "2025-05-20",
                "total_suply_hs_shl": 45,
                "suply_amount": 52000,
                "builder": "GS건설",
                "region_code": "11",
                "pblanc_knd": "아파트",
                "units_info": [
                    {"model_no": "1", "house_type": "전용 59", "supply_area": "59.0", "price": 48000, "households": 25},
                    {"model_no": "2", "house_type": "전용 84", "supply_area": "84.0", "price": 55000, "households": 20},
                ],
            },
            # UNSOLD 시나리오: 본청약/공공분양 (예: 역곡지구 하우스토리 신혼희망타운)
            {
                "pblanc_no": "2025001022",
                "house_nm": "역곡지구 하우스토리(부천역곡지구 A-2BL) 신혼희망타운(공공분양)(본청약)",
                "suply_location": "경기도 부천시",
                "rcrit_pblanc_de": "2025-02-10",
                "total_suply_hs_shl": 320,
                "suply_amount": 35000,
                "builder": "한국토지주택공사",
                "region_code": "41",
                "pblanc_knd": "공공분양",
                "units_info": [
                    {"model_no": "1", "house_type": "전용 51", "supply_area": "51.0", "price": 28000, "households": 160},
                    {"model_no": "2", "house_type": "전용 59", "supply_area": "59.0", "price": 32000, "households": 160},
                ],
            },
        ]

        if region:
            region_prefix = region[:2] if len(region) >= 2 else region
            mock_data = [
                item for item in mock_data
                if item.get("region_code", "").startswith(region_prefix)
            ]

        result = [self._to_listing(item) for item in mock_data]
        for listing in result:
            for u in listing.units_info:
                area = u.get("supply_area")
                if area:
                    try:
                        a = float(area)
                        if a > 0:
                            u["price_per_m2"] = round(u["price"] / a, 0)
                            u["price_per_pyung"] = round(u["price"] / a * 3.3058, 0)
                    except (ValueError, TypeError):
                        pass
        return result

    def _to_listing(self, item: dict[str, Any]) -> SaleListing:
        """API 응답 아이템을 SaleListing으로 변환합니다."""
        name = item.get("HOUSE_NM") or item.get("house_nm") or "알 수 없음"
        location = item.get("HSSPLY_ADRES") or item.get("suply_location") or ""
        units = int(item.get("TOT_SUPLY_HSHLDCO") or item.get("total_suply_hs_shl") or 0)
        price = int(item.get("suply_amount", 0) or 0)
        builder = item.get("CNSTRCT_ENTRPS_NM") or item.get("builder") or ""
        region_code = item.get("SUBSCRPT_AREA_CODE") or item.get("region_code") or ""

        house_type = item.get("HOUSE_SECD_NM") or item.get("HOUSE_DTL_SECD_NM") or item.get("pblanc_knd") or ""
        if "아파트" in house_type or "분양" in house_type:
            supply_type = SupplyType.APT
        elif "공공" in house_type or "행복" in name or "신혼" in house_type:
            supply_type = SupplyType.PUBLIC
        else:
            supply_type = SupplyType.APT

        announcement_date = item.get("RCRIT_PBLANC_DE") or item.get("rcrit_pblanc_de") or ""
        status = self._estimate_status(announcement_date, name)

        region_name = REGION_CODE_MAP.get(region_code[:2], "")
        if location and not region_name:
            region_name = location.split()[0] if location else ""

        units_info = item.get("units_info") or []

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
            units_info=units_info,
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
            unsold_keywords = ["미분양", "잔여", "무순위", "취소", "보류지"]
            if any(kw in name for kw in unsold_keywords):
                return SaleStatus.UNSOLD
            return SaleStatus.CLOSED
