"""브랜드 점수 테스트."""
from __future__ import annotations

from src.housing.analyzer.brand_scores import BRAND_SCORES, get_brand_score


class TestBrandScores:
    def test_brand_count(self):
        """브랜드 30개 이상."""
        assert len(BRAND_SCORES) >= 30, f"Only {len(BRAND_SCORES)} brands"

    def test_gs_score_in_range(self):
        """GS건설 점수 0-100 범위."""
        score = get_brand_score("GS건설")
        assert 0 <= score <= 100
        assert score >= 80  # Top 건설사

    def test_lh_score_reasonable(self):
        """LH 공기업 점수 합리적."""
        score = get_brand_score("LH")
        assert 0 <= score <= 100
        assert 50 <= score <= 80  # 공기업은 중상위

    def test_unknown_brand_default(self):
        """알 수 없는 브랜드는 기본 50점."""
        score = get_brand_score("존재하지않는건설")
        assert score == 50.0

    def test_partial_match(self):
        """부분 일치 검색."""
        # 정확히 일치하지 않아도 비슷하면 매칭
        score = get_brand_score("GS건설(자이)")
        assert 0 <= score <= 100

    def test_overrides(self):
        """오버라이드 적용."""
        overrides = {"GS건설": 50.0}
        score = get_brand_score("GS건설", overrides)
        assert score == 50.0
