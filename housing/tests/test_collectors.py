"""데이터 수집기 테스트."""
from __future__ import annotations

from src.housing.collectors.cheongyak import CheongyakCollector
from src.housing.collectors.lh import LHCollector
from src.housing.collectors.naver import NaverCollector
from src.housing.collectors.molit import MolitTradeCollector


class TestCheongyakCollector:
    def test_mock_collection(self):
        """Mock 수집 검증."""
        c = CheongyakCollector()
        listings = c.collect(mock=True)
        assert len(listings) > 0
        assert all(l.source == "cheongyak" for l in listings)
        assert all(l.name for l in listings)

    def test_mock_region_filter(self):
        """지역 필터 적용."""
        c = CheongyakCollector()
        seoul_listings = c.collect(region="11", mock=True)
        busan_listings = c.collect(region="26", mock=True)
        assert len(seoul_listings) >= len(busan_listings)

    def test_model_conversion(self):
        """SaleListing 변환 검증."""
        c = CheongyakCollector()
        listings = c.collect(mock=True)
        for l in listings:
            assert hasattr(l, 'name')
            assert hasattr(l, 'region')
            assert hasattr(l, 'price')
            assert hasattr(l, 'units')


class TestLHCollector:
    def test_mock_collect_apt(self):
        """LH 분양 Mock 수집."""
        c = LHCollector()
        listings = c.collect_apt(mock=True)
        assert len(listings) > 0
        for l in listings:
            assert l.source == "lh"

    def test_mock_collect_land(self):
        """LH 택지 Mock 수집."""
        c = LHCollector()
        listings = c.collect_land(mock=True)
        assert len(listings) > 0

    def test_collect_total(self):
        """전체 수집 = 분양 + 택지."""
        c = LHCollector()
        total = c.collect(mock=True)
        apt = c.collect_apt(mock=True)
        land = c.collect_land(mock=True)
        assert len(total) == len(apt) + len(land)



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


class TestNaverCollector:
    def test_mock_collection(self):
        """네이버 Mock 수집."""
        c = NaverCollector()
        listings = c.collect(mock=True)
        assert len(listings) > 0
        assert all(l.source == "naver" for l in listings)
