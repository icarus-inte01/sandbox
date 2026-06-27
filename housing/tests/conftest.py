"""pytest fixtures."""
from __future__ import annotations

import pytest

from src.housing.models import SaleListing, SupplyType, SaleStatus, TradeRecord


@pytest.fixture
def sample_listing() -> SaleListing:
    return SaleListing(
        name="테스트아파트",
        region="서울특별시 강남구",
        supply_type=SupplyType.APT,
        status=SaleStatus.PLANNED,
        units=500,
        price=80000,
        builder="GS건설",
        source="cheongyak",
        discount_rate=15.0,
        competition_rate=10.0,
    )


@pytest.fixture
def sample_listings() -> list[SaleListing]:
    return [
        SaleListing(name="강남자이", region="서울특별시 강남구", supply_type=SupplyType.APT,
                    status=SaleStatus.PLANNED, units=850, price=85000, builder="GS건설",
                    discount_rate=18.0, competition_rate=25.0),
        SaleListing(name="LH행복", region="경기도 화성시", supply_type=SupplyType.PUBLIC,
                    status=SaleStatus.OPEN, units=350, price=28000, builder="LH",
                    discount_rate=5.0, competition_rate=3.0),
        SaleListing(name="지방A", region="전라남도 목포시", supply_type=SupplyType.APT,
                    status=SaleStatus.CLOSED, units=150, price=22000, builder="기타",
                    discount_rate=-10.0, competition_rate=0.5),
    ]


@pytest.fixture
def sample_trade() -> TradeRecord:
    return TradeRecord(
        apartment_name="은마아파트",
        price=150000,
        area=84.5,
        contract_date="20260615",
        floor=8,
        build_year=1988,
        region_code="11680",
        region_name="서울 강남구",
    )
