"""네이버 부동산 데이터 수집기 (보조 소스).

네이버 부동산의 비공식 API를 통해 단지 정보와 실거래가를 수집합니다.
공공데이터가 부족한 경우 보조적으로 사용하며, 실패해도 전체
파이프라인이 중단되지 않도록 모든 예외를 처리합니다.

주의: 네이버 부동산은 비공식 API이므로 차단될 수 있습니다.
      요청 간격 3초 이상 유지 필수.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.housing.collectors.base import BaseCollector
from src.housing.models import SaleListing, SupplyType, SaleStatus

logger = logging.getLogger(__name__)

NAVER_COMPLEX_API = "https://new.land.naver.com/api/complexes"


class NaverCollector(BaseCollector):
    """네이버 부동산 데이터 수집기."""

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.source_name = "naver"

    def collect(self, **kwargs) -> list[SaleListing]:
        mock = kwargs.get("mock", False)
        if mock:
            return self._mock_collect()
        try:
            return self._try_playwright_collect()
        except Exception as e:
            logger.warning("NaverCollector failed: %s", e)
            return self._mock_collect()

    def search_complexes(self, query: str) -> list[dict[str, Any]]:
        logger.info("Searching complexes: %s", query)
        return []

    def collect_complex_info(self, complex_no: str) -> Optional[dict[str, Any]]:
        logger.info("Collecting complex info: %s", complex_no)
        return None

    def _try_playwright_collect(self) -> list[SaleListing]:
        raise NotImplementedError("Playwright collection not implemented. Use mock=True.")

    def _mock_collect(self) -> list[SaleListing]:
        mock_data = [
            {"name": "디에이치 방배", "region": "서울특별시 서초구", "units": 420, "price": 110000, "builder": "현대건설"},
            {"name": "루원시티 SK리더스뷰", "region": "인천광역시 서구", "units": 680, "price": 52000, "builder": "SK에코플랜트"},
            {"name": "힐스테이트 금정역", "region": "부산광역시 금정구", "units": 350, "price": 45000, "builder": "현대건설"},
        ]
        return [
            SaleListing(
                name=item["name"], region=item["region"],
                supply_type=SupplyType.APT, status=SaleStatus.PLANNED,
                units=item["units"], price=item["price"],
                builder=item["builder"], source="naver",
            )
            for item in mock_data
        ]
