"""모델 검증 테스트."""
from __future__ import annotations

from src.housing.models import SaleListing, SupplyType, SaleStatus, TradeRecord


class TestSaleListing:
    def test_create_default(self):
        """SaleListing 기본 생성."""
        listing = SaleListing(name="테스트", region="서울")
        assert listing.name == "테스트"
        assert listing.region == "서울"
        assert listing.supply_type == SupplyType.OTHER
        assert listing.status == SaleStatus.PLANNED
        assert listing.units == 0
        assert listing.price == 0

    def test_create_full(self):
        """SaleListing 모든 필드 생성."""
        listing = SaleListing(
            name="래미안", region="서울", supply_type=SupplyType.APT,
            status=SaleStatus.OPEN, units=500, price=80000,
            builder="삼성물산", discount_rate=15.0, total_score=85.0,
            source="cheongyak",
        )
        assert listing.name == "래미안"
        assert listing.supply_type == SupplyType.APT
        assert listing.status == SaleStatus.OPEN
        assert listing.total_score == 85.0

    def test_supply_type_values(self):
        """SupplyType 모든 값 확인."""
        assert SupplyType.APT.value == "apt"
        assert SupplyType.PUBLIC.value == "public"
        assert SupplyType.LAND.value == "land"
        assert SupplyType.SH.value == "sh"

    def test_sale_status_values(self):
        """SaleStatus 모든 값 확인."""
        assert SaleStatus.PLANNED.value == "planned"
        assert SaleStatus.OPEN.value == "open"
        assert SaleStatus.CLOSED.value == "closed"
        assert SaleStatus.UNSOLD.value == "unsold"


class TestTradeRecord:
    def test_create(self):
        """TradeRecord 생성."""
        trade = TradeRecord(
            apartment_name="아파트", price=50000, area=84.5,
            contract_date="202606", floor=10, build_year=2020,
            region_code="11110", region_name="종로구",
        )
        assert trade.apartment_name == "아파트"
        assert trade.price == 50000
        assert trade.area == 84.5
