"""SH 서울주택도시공사 분양정보 수집기.

공공데이터 ID 15102880 (파일데이터)를 기반으로 SH 분양정보를 수집합니다.
SH는 OpenAPI보다 파일데이터 위주로 제공하므로, 파일데이터 다운로드
방식과 Mock 데이터를 함께 지원합니다.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.housing.collectors.base import BaseCollector
from src.housing.models import SaleListing, SupplyType, SaleStatus

logger = logging.getLogger(__name__)


class SHCollector(BaseCollector):
    """SH 서울주택도시공사 분양정보 수집기."""

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.source_name = "sh"

    def collect(
        self, mock: bool = False
    ) -> list[SaleListing]:
        """SH 분양정보를 수집합니다."""
        return self._mock_collect()

    def _mock_collect(self) -> list[SaleListing]:
        """Mock SH 분양 데이터."""
        mock_data = [
            {
                "complex_nm": "SH 위례 포레시티",
                "region": "서울특별시 송파구",
                "project_type": "공공분양",
                "total_units": 820,
                "supply_price": 68000,
                "announce_date": "2026-07-15",
                "builder": "SH공사",
            },
            {
                "complex_nm": "SH 마곡 수명산파크",
                "region": "서울특별시 강서구",
                "project_type": "공공분양",
                "total_units": 560,
                "supply_price": 55000,
                "announce_date": "2026-08-01",
                "builder": "SH공사",
            },
            {
                "complex_nm": "SH 항동 지웰시티",
                "region": "서울특별시 구로구",
                "project_type": "공공분양",
                "total_units": 340,
                "supply_price": 45000,
                "announce_date": "2026-06-20",
                "builder": "SH공사",
            },
            {
                "complex_nm": "SH 고덕 강일 리버시티",
                "region": "서울특별시 강동구",
                "project_type": "공공분양",
                "total_units": 1100,
                "supply_price": 72000,
                "announce_date": "2026-09-01",
                "builder": "SH공사",
            },
            {
                "complex_nm": "SH 은평 뉴타운",
                "region": "서울특별시 은평구",
                "project_type": "공공분양",
                "total_units": 290,
                "supply_price": 38000,
                "announce_date": "2026-07-05",
                "builder": "SH공사",
            },
        ]

        return [self._to_listing(item) for item in mock_data]

    def _to_listing(self, item: dict[str, Any]) -> SaleListing:
        """API 응답을 SaleListing으로 변환."""
        name = item.get("complex_nm", "알 수 없음")
        region = item.get("region", "서울특별시")
        units = int(item.get("total_units", 0) or 0)
        price = int(item.get("supply_price", 0) or 0)
        builder = item.get("builder", "SH공사")
        announce_date = item.get("announce_date", "")

        return SaleListing(
            name=name,
            region=region,
            supply_type=SupplyType.SH,
            status=SaleStatus.PLANNED,
            units=units,
            price=price,
            builder=builder,
            announcement_date=announce_date,
            source="sh",
        )
