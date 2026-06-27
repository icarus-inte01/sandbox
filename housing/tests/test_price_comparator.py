"""분양가 할인율 계산 테스트."""
from __future__ import annotations

from src.housing.analyzer.price_comparator import (
    calculate_discount_rate,
    score_from_discount,
    calculate_discount_on_listing,
)
from src.housing.models import SaleListing, SupplyType


class TestDiscountRate:
    def test_positive_discount(self):
        """분양가 < 시세 → 할인율 양수."""
        rate = calculate_discount_rate(50000, 60000)
        assert rate is not None
        assert rate > 0
        assert rate == 16.7  # (60000-50000)/60000 * 100

    def test_zero_discount(self):
        """분양가 == 시세 → 할인율 0%."""
        rate = calculate_discount_rate(50000, 50000)
        assert rate == 0.0

    def test_negative_discount(self):
        """분양가 > 시세 → 할인율 음수."""
        rate = calculate_discount_rate(70000, 50000)
        assert rate is not None
        assert rate < 0

    def test_invalid_price(self):
        """유효하지 않은 가격 → None."""
        assert calculate_discount_rate(0, 50000) is None
        assert calculate_discount_rate(50000, 0) is None

    def test_high_discount_max_score(self):
        """할인율 20% 이상 → 100점."""
        assert score_from_discount(25.0) == 100.0
        assert score_from_discount(20.0) == 100.0

    def test_zero_discount_score(self):
        """할인율 0% → 50점."""
        assert score_from_discount(0.0) == 50.0

    def test_negative_discount_low_score(self):
        """할인율 마이너스 → 낮은 점수."""
        score = score_from_discount(-20.0)
        assert score <= 30.0  # 낮은 점수 (정확한 값은 25.0)

    def test_none_discount_mid_score(self):
        """데이터 없음 → 중립 50점."""
        assert score_from_discount(None) == 50.0

    def test_calculate_on_listing(self):
        """SaleListing 기준 할인율 계산."""
        listing = SaleListing(name="테스트", region="서울", price=50000, units=100)
        prices = {"avg_price": 65000, "avg_price_per_area": 0, "min_price": 0,
                  "max_price": 0, "trade_count": 1, "trades": [], "region_code": ""}
        rate, score = calculate_discount_on_listing(listing, prices)
        assert rate is not None
        assert rate > 0
        assert 0 <= score <= 100
