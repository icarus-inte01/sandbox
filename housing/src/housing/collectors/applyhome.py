"""청약홈 분양정보 수집기.

공공데이터 API ID 15098547 (ApplyhomeInfoDetailSvc)를 사용하여
전국 아파트 분양공고 정보를 수집합니다.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Optional

from src.housing.analyzer.region_data import REGION_CODE_MAP
from src.housing.collectors.base import BaseCollector
from src.housing.models import SaleListing, SupplyType, SaleStatus

logger = logging.getLogger(__name__)


API_BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
API_LIST = f"{API_BASE}/getAPTLttotPblancDetail"
API_MDL = f"{API_BASE}/getAPTLttotPblancMdl"

# 서버 cond[HOUSE_NM::LIKE] 미분양 검색 키워드
# (잔여/취소분/보류지 매칭; 미분양·무순위 명칭은 현재 API 데이터에 0건이라 제외)
UNSOLD_SEARCH_KEYWORDS = ("잔여", "취소", "보류지")


def _sum_households(model: dict[str, Any]) -> int:
    return (
        int(model.get("SUPLY_HSHLDCO", 0) or 0)
        + int(model.get("SPSPLY_HSHLDCO", 0) or 0)
        + int(model.get("ETC_HSHLDCO", 0) or 0)
        + int(model.get("NWWDS_HSHLDCO", 0) or 0)
        + int(model.get("NWBB_HSHLDCO", 0) or 0)
    )


class ApplyhomeCollector(BaseCollector):
    """청약홈 분양정보 수집기."""

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.source_name = "applyhome"

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
            raise RuntimeError(
                "DATA_GO_KR_API_KEY not configured. "
                "Set DATA_GO_KR_API_KEY env var or use mock=True (--mock) explicitly."
            )

        try:
            now = datetime.now()

            # 서버 측 cond 필터로 접수 가능한 항목만 조회 (전체 2,851건 중 대상만 수신)
            # 1) 접수 가능(PLANNED+OPEN): 접수종료일(RCEPT_ENDDE)이 오늘 이후
            # 2) 미분양 잔여분(UNSOLD): 공고일(RCRIT_PBLANC_DE) 365일 이내 + 이름 키워드
            #    cond[HOUSE_NM::LIKE]는 단일 키워드만 매칭되므로 키워드별 개별 호출 (AND 결합 확인됨)
            today = now.strftime("%Y-%m-%d")
            cutoff_365 = (now - timedelta(days=365)).strftime("%Y-%m-%d")

            def _collect_with(params: dict) -> list[dict]:
                if region:
                    params["cond[SUBSCRPT_AREA_CODE::EQ]"] = region
                return self.client.fetch_all(API_LIST, params, max_pages=5)

            # 1) 접수 가능: 접수종료일이 오늘 이후 (PLANNED + OPEN)
            detail_items = _collect_with({
                "page": 1, "perPage": 100,
                "cond[RCEPT_ENDDE::GTE]": today,
            })

            # 2) 미분양 잔여분: 공고 365일 이내 + 이름 키워드별 LIKE
            for keyword in UNSOLD_SEARCH_KEYWORDS:
                detail_items.extend(_collect_with({
                    "page": 1, "perPage": 100,
                    "cond[RCRIT_PBLANC_DE::GTE]": cutoff_365,
                    "cond[HOUSE_NM::LIKE]": keyword,
                }))

            # 접수가능 쿼리와 미분양 쿼리 간 중복 제거 (HOUSE_MANAGE_NO 기준)
            seen: set[str] = set()
            unique_items: list[dict] = []
            for item in detail_items:
                key = item.get("HOUSE_MANAGE_NO", "")
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                unique_items.append(item)
            detail_items = unique_items

            logger.info("서버 필터 조회: 접수가능+미분양 %d건", len(detail_items))

            # detail Items의 house_manage_no만 model에서 조회
            target_keys = {item.get("HOUSE_MANAGE_NO", "") for item in detail_items if item.get("HOUSE_MANAGE_NO")}

            model_items: list[dict] = []
            if target_keys:
                # model 엔드포인트도 cond[HOUSE_MANAGE_NO::EQ] 서버 필터 지원 → 순차 페이지 스캔 대신 병렬 개별 조회
                def _fetch_models(key: str) -> list[dict]:
                    result = self.client.fetch(API_MDL, {
                        "page": 1, "perPage": 100,
                        "cond[HOUSE_MANAGE_NO::EQ]": key,
                    })
                    return result.get("data", [])

                try:
                    with ThreadPoolExecutor(max_workers=8) as executor:
                        for batch in executor.map(_fetch_models, sorted(target_keys)):
                            model_items.extend(batch)
                    logger.info(
                        "Model detail 커버: %d개 단지, cond 필터 병렬 조회 %d건",
                        len(target_keys), len(model_items),
                    )
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
            logger.error("Applyhome API call failed: %s", e)
            raise

    def _mock_collect(self, region: Optional[str] = None) -> list[SaleListing]:
        """Mock 분양 데이터를 생성합니다."""
        mock_data = [
            {
                "pblanc_no": "2026001001",
                "house_nm": "래미안 원펜타스",
                "suply_location": "서울특별시 서초구",
                "rcrit_pblanc_de": "2026-07-15",
                "rcpt_bgnde": "2026-08-24",
                "rcpt_endde": "2026-08-26",
                "total_suply_hs_shl": 1024,
                "suply_amount": 85000,
                "builder": "삼성물산",
                "region_code": "100",
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
                "rcpt_bgnde": "2026-08-24",
                "rcpt_endde": "2026-08-27",
                "total_suply_hs_shl": 320,
                "suply_amount": 95000,
                "builder": "현대건설",
                "region_code": "100",
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
                "rcpt_bgnde": "2026-08-14",
                "rcpt_endde": "2026-08-16",
                "total_suply_hs_shl": 680,
                "suply_amount": 72000,
                "builder": "GS건설",
                "region_code": "410",
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
                "rcpt_bgnde": "2026-08-12",
                "rcpt_endde": "2026-08-13",
                "total_suply_hs_shl": 950,
                "suply_amount": 42000,
                "builder": "대림산업",
                "region_code": "410",
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
                "rcpt_bgnde": "2026-08-10",
                "rcpt_endde": "2026-08-11",
                "total_suply_hs_shl": 450,
                "suply_amount": 32000,
                "builder": "한화건설",
                "region_code": "312",
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
                "region_code": "560",
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
                "region_code": "500",
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
                "region_code": "100",
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
                "region_code": "410",
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

        # RCRIT_PBLANC_DE: 공고일, RCEPT_BGNDE: 청약 접수 시작일, RCEPT_ENDDE: 청약 접수 종료일
        announcement_date = item.get("RCRIT_PBLANC_DE") or item.get("rcrit_pblanc_de") or ""
        reception_start = item.get("RCEPT_BGNDE") or item.get("rcpt_bgnde") or ""
        reception_end = item.get("RCEPT_ENDDE") or item.get("rcpt_endde") or ""
        status = self._estimate_status(announcement_date, name, reception_start, reception_end)

        region_name = REGION_CODE_MAP.get(region_code, "")
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
            source="applyhome",
            units_info=units_info,
        )

    def _estimate_status(
        self,
        announcement_date: str,
        name: str,
        reception_start: str = "",
        reception_end: str = "",
    ) -> SaleStatus:
        """접수기간(RCEPT_BGNDE/ENDDE) 기준으로 분양상태를 판정합니다.

        접수기간 필드가 있으면 실제 청약 접수 기간으로 판정하고,
        없으면 공고일 기준 추정으로 fallback합니다.

        판정 규칙 (접수기간 기준):
            now < 시작일        → PLANNED (분양예정)
            시작일 ≤ now ≤ 종료일 → OPEN    (접수 진행중)
            now > 종료일        → CLOSED  (접수 마감, 미분양 키워드 시 UNSOLD)
        """
        start_dt = self._parse_date(reception_start)
        end_dt = self._parse_date(reception_end)
        if start_dt and end_dt:
            now = datetime.now()
            if now < start_dt:
                return SaleStatus.PLANNED
            if now <= end_dt:
                return SaleStatus.OPEN
            if self._is_unsold(name):
                return SaleStatus.UNSOLD
            return SaleStatus.CLOSED

        if not announcement_date:
            return SaleStatus.PLANNED

        announcement = self._parse_date(announcement_date)
        if not announcement:
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
            if self._is_unsold(name):
                return SaleStatus.UNSOLD
            return SaleStatus.CLOSED

    @staticmethod
    def _parse_date(value: str) -> Optional[datetime]:
        value = str(value).strip() if value else ""
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _is_unsold(name: str) -> bool:
        unsold_keywords = ["미분양", "잔여", "무순위", "취소", "보류지"]
        return any(kw in name for kw in unsold_keywords)
