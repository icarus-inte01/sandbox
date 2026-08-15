"""데이터 수집기 테스트."""
from __future__ import annotations

from src.housing.collectors.applyhome import ApplyhomeCollector
from src.housing.collectors.lh import LHCollector


from src.housing.collectors.molit import MolitTradeCollector

class TestApplyhomeCollector:
    def test_mock_collection(self):
        """Mock 수집 검증."""
        c = ApplyhomeCollector()
        listings = c.collect(mock=True)
        assert len(listings) > 0
        assert all(l.source == "applyhome" for l in listings)
        assert all(l.name for l in listings)

    def test_mock_region_filter(self):
        """지역 필터 적용 (청약홈 3-digit SUBSCRPT_AREA_CODE)."""
        c = ApplyhomeCollector()
        seoul_listings = c.collect(region="100", mock=True)
        busan_listings = c.collect(region="600", mock=True)
        assert len(seoul_listings) >= len(busan_listings)

    def test_model_conversion(self):
        """SaleListing 변환 검증."""
        c = ApplyhomeCollector()
        listings = c.collect(mock=True)
        for l in listings:
            assert hasattr(l, 'name')
            assert hasattr(l, 'region')
            assert hasattr(l, 'price')
            assert hasattr(l, 'units')

    def test_estimate_status_reception_period(self):
        """접수기간(RCEPT_BGNDE/ENDDE) 기준 상태 판정."""
        from src.housing.models import SaleStatus
        from datetime import datetime, timedelta
        c = ApplyhomeCollector()
        today = datetime.now()
        d = lambda days: (today + timedelta(days=days)).strftime("%Y-%m-%d")

        # 접수 시작 전 → PLANNED
        assert c._estimate_status(d(-10), "테스트단지", d(3), d(5)) == SaleStatus.PLANNED
        # 접수 진행 중 → OPEN
        assert c._estimate_status(d(-10), "테스트단지", d(-1), d(1)) == SaleStatus.OPEN
        # 접수 종료 → CLOSED
        assert c._estimate_status(d(-10), "테스트단지", d(-5), d(-1)) == SaleStatus.CLOSED
        # 접수 종료 + 미분양 키워드 → UNSOLD
        assert c._estimate_status(d(-10), "잔여세대 무순위", d(-5), d(-1)) == SaleStatus.UNSOLD

    def test_estimate_status_fallback(self):
        """접수기간 필드 없을 때 공고일 기준 fallback."""
        from src.housing.models import SaleStatus
        from datetime import datetime, timedelta
        c = ApplyhomeCollector()
        today = datetime.now()
        d = lambda days: (today + timedelta(days=days)).strftime("%Y-%m-%d")

        assert c._estimate_status(d(5), "테스트단지") == SaleStatus.PLANNED
        assert c._estimate_status(d(-10), "테스트단지") == SaleStatus.OPEN
        assert c._estimate_status(d(-60), "테스트단지") == SaleStatus.CLOSED
        assert c._estimate_status(d(-400), "미분양 아파트") == SaleStatus.UNSOLD
        assert c._estimate_status("", "테스트단지") == SaleStatus.PLANNED


class TestLHCollector:
    def test_mock_collect_land(self):
        """LH 택지 Mock 수집."""
        c = LHCollector()
        listings = c.collect_land(mock=True)
        assert len(listings) > 0
        for l in listings:
            assert l.source == "lh"

    def test_collect_total(self):
        """전체 수집 = 택지 (분양은 applyhome으로 대체)."""
        c = LHCollector()
        total = c.collect(mock=True)
        land = c.collect_land(mock=True)
        assert len(total) == len(land)



class TestMolitCollector:
    def test_mock_trades(self):
        """실거래가 Mock 수집."""
        c = MolitTradeCollector()
        trades = c.collect_trades("11680", "202606", mock=True)
        assert len(trades) > 0

    def test_mock_nearby_prices(self):
        """주변 시세 Mock 집계."""
        c = MolitTradeCollector()
        prices = c.get_nearby_prices("11680", months_back=3, mock=True)
        assert prices["avg_price"] > 0
        assert prices["trade_count"] > 0

    def test_price_parsing(self):
        """거래금액 파싱."""
        c = MolitTradeCollector()
        assert c._parse_price("50000") == 50000
        assert c._parse_price("50,000") == 50000
        assert c._parse_price("5억") == 50000
        assert c._parse_price("5억5000") == 55000
        assert c._parse_price("") == 0



