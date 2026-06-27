"""지역/교통 점수 테스트."""
from __future__ import annotations

from src.housing.analyzer.region_data import REGION_SCORES, get_region_score


class TestRegionScores:
    def test_region_count(self):
        """지역 50개 이상."""
        assert len(REGION_SCORES) >= 50, f"Only {len(REGION_SCORES)} regions"

    def test_seoul_top_score(self):
        """서울 최상위 점수."""
        score = get_region_score("서울특별시")
        assert score >= 90

    def test_subway_bonus(self):
        """강남구 역세권 가산점."""
        score = get_region_score("서울특별시 강남구")
        assert score > get_region_score("서울특별시")
        assert score <= 100

    def test_rural_lower_score(self):
        """지방 도시 낮은 점수."""
        big_city = get_region_score("서울특별시")
        rural = get_region_score("강원도")
        assert rural < big_city

    def test_unknown_default(self):
        """알 수 없는 지역 기본 50점."""
        score = get_region_score("존재하지않는지역")
        assert score == 50.0

    def test_overrides(self):
        """오버라이드 적용."""
        overrides = {"서울특별시": 50.0}
        score = get_region_score("서울특별시", overrides)
        assert score == 50.0
