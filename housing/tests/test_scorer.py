"""종합 점수 계산 테스트."""
from __future__ import annotations

from src.housing.analyzer.scorer import calculate_score, calculate_scores_batch
from src.housing.analyzer.ranker import rank_listings, top_n
from src.housing.models import SaleListing, SupplyType, SaleStatus


class TestScorer:
    def test_score_range(self, sample_listing):
        """점수 0-100 범위."""
        score = calculate_score(sample_listing)
        assert 0 <= score <= 100

    def test_prime_listing_high_score(self):
        """프라임 매물 높은 점수."""
        listing = SaleListing(
            name="프라임", region="서울특별시 강남구",
            supply_type=SupplyType.APT, status=SaleStatus.PLANNED,
            units=1000, price=80000, builder="GS건설",
            discount_rate=20.0, competition_rate=30.0,
        )
        score = calculate_score(listing)
        assert score >= 80  # 매우 높은 점수

    def test_poor_listing_low_score(self):
        """비프라임 매물 낮은 점수."""
        listing = SaleListing(
            name="비프라임", region="강원도",
            supply_type=SupplyType.APT, status=SaleStatus.PLANNED,
            units=50, price=30000, builder="무명건설",
            discount_rate=-15.0, competition_rate=0.1,
        )
        score = calculate_score(listing)
        assert score <= 50  # 낮은 점수

    def test_custom_weights(self):
        """커스텀 가중치 적용."""
        listing = SaleListing(
            name="테스트", region="서울", supply_type=SupplyType.APT,
            status=SaleStatus.PLANNED, units=500, price=50000, builder="GS건설",
            discount_rate=10.0, competition_rate=10.0,
        )
        weights = {"discount_rate": 1.0, "transit_location": 0.0,
                   "brand": 0.0, "competition": 0.0, "scale": 0.0}
        score = calculate_score(listing, weights)
        assert score > 0

    def test_scores_saved_on_listing(self, sample_listing):
        """점수가 listing 객체에 저장됨."""
        calculate_score(sample_listing)
        assert sample_listing.discount_rate == 15.0
        assert sample_listing.transit_score is not None
        assert sample_listing.brand_score is not None
        assert sample_listing.competition_score is not None
        assert sample_listing.scale_score is not None
        assert sample_listing.total_score is not None


class TestRanker:
    def test_rank_descending(self, sample_listings):
        """점수 내림차순 정렬."""
        scored = calculate_scores_batch(sample_listings)
        ranked = rank_listings(scored)
        scores = [l.total_score or 0 for l in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_top_n(self, sample_listings):
        """상위 N개 필터."""
        scored = calculate_scores_batch(sample_listings)
        top = top_n(scored, n=2)
        assert len(top) == 2

    def test_top_n_with_min_score(self, sample_listings):
        """최소 점수 필터."""
        scored = calculate_scores_batch(sample_listings)
        top = top_n(scored, n=10, min_score=70)
        for l in top:
            assert (l.total_score or 0) >= 70
