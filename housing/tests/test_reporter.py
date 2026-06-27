"""리포트 렌더링 테스트."""
from __future__ import annotations

from src.housing.reporter.email_renderer import render_report, _score_color, _krw_format
from src.housing.models import SaleListing, SupplyType, SaleStatus


class TestScoreColor:
    def test_high_score_green(self):
        """80점 이상 녹색."""
        assert _score_color(85) == "#1a7a3a"

    def test_mid_score_yellow(self):
        """60-69점 노란색."""
        assert _score_color(65) == "#e6a817"

    def test_low_score_red(self):
        """60점 미만 빨간색."""
        assert _score_color(40) == "#b91c1c"

    def test_none_color_gray(self):
        """None은 회색."""
        assert _score_color(None) == "#999999"


class TestKrwFormat:
    def test_50000(self):
        """5억만원 포맷."""
        assert _krw_format(50000) == "5억0만원"

    def test_85000(self):
        """8억5천만원 포맷."""
        assert _krw_format(85000) == "8억5,000만원"

    def test_500(self):
        """500만원 포맷."""
        assert _krw_format(500) == "500만원"

    def test_none(self):
        """None은 '-'."""
        assert _krw_format(None) == "-"


class TestRenderReport:
    def test_render_empty(self):
        """빈 리스트 렌더링."""
        html = render_report([], "2026-06-27")
        assert len(html) > 500
        assert "<table" in html or "분양정보가 없습니다" in html
        assert "</html>" in html

    def test_render_with_data(self):
        """데이터 포함 렌더링."""
        listings = [
            SaleListing(name="테스트단지", region="서울", supply_type=SupplyType.APT,
                        status=SaleStatus.PLANNED, units=500, price=80000,
                        builder="GS건설", total_score=90.0, discount_rate=15.0),
        ]
        html = render_report(listings, "2026-06-27")
        assert "테스트단지" in html
        assert "GS건설" in html
        assert "90" in html
        assert "서울" in html

    def test_header_contains_date(self):
        """헤더에 날짜 포함."""
        html = render_report([], "2026-06-27")
        assert "2026-06-27" in html

    def test_disclaimer_present(self):
        """면책 문구 포함."""
        html = render_report([], "2026-06-27", include_notes=True)
        assert "참고용" in html or "면책" in html or "매수 추천" in html
