"""HTML 리포트 생성기 테스트."""
from __future__ import annotations

import os

import pytest

from src.tour.models import TourItem, TourReport
from src.tour.reporter.generator import ReportGenerator


@pytest.fixture
def sample_report() -> TourReport:
    """테스트용 TourReport fixture."""
    report = TourReport(region="서울", date="2026-07-11")
    report.categories["관광지"] = [
        TourItem(
            content_id="1",
            content_type_id=12,
            title="경복궁",
            addr1="서울 종로구",
            overview="조선시대 대표 궁궐",
        ),
        TourItem(
            content_id="2",
            content_type_id=12,
            title="북촌한옥마을",
            addr1="서울 종로구",
        ),
    ]
    report.categories["음식점"] = [
        TourItem(
            content_id="3",
            content_type_id=39,
            title="광장시장",
            addr1="서울 종로구",
            tel="02-1234-5678",
        ),
    ]
    report.categories["축제/행사"] = []
    report.categories["문화시설"] = []
    report.categories["숙박"] = []
    return report


class TestReportGenerator:
    """ReportGenerator 테스트."""

    def test_render_returns_html(self, sample_report: TourReport) -> None:
        gen = ReportGenerator()
        html = gen.render(sample_report)
        assert isinstance(html, str)
        assert len(html) > 0
        assert "서울" in html
        assert "2026-07-11" in html

    def test_render_contains_title(self, sample_report: TourReport) -> None:
        gen = ReportGenerator()
        html = gen.render(sample_report)
        assert "여행정보 리포트" in html

    def test_render_contains_categories(self, sample_report: TourReport) -> None:
        gen = ReportGenerator()
        html = gen.render(sample_report)
        assert "관광지" in html
        assert "음식점" in html

    def test_render_contains_items(self, sample_report: TourReport) -> None:
        gen = ReportGenerator()
        html = gen.render(sample_report)
        assert "경복궁" in html
        assert "광장시장" in html

    def test_render_empty_category(self) -> None:
        report = TourReport(region="테스트", date="2026-01-01")
        report.categories["관광지"] = []
        gen = ReportGenerator()
        html = gen.render(report)
        assert "데이터가 없습니다" in html

    def test_save_html(self, sample_report: TourReport, tmp_path) -> None:
        output_path = os.path.join(str(tmp_path), "report.html")
        gen = ReportGenerator()
        html = gen.render(sample_report)
        saved_path = gen.save_html(html, output_path)
        assert os.path.exists(output_path)
        assert saved_path == os.path.abspath(output_path)
        with open(output_path, "r") as f:
            content = f.read()
        assert "경복궁" in content

    def test_render_all_five_categories(self) -> None:
        report = TourReport(region="부산", date="2026-08-15")
        cat_names = ["관광지", "음식점", "축제/행사", "문화시설", "숙박"]
        for name in cat_names:
            report.categories[name] = [
                TourItem(content_id="1", content_type_id=12, title=f"{name} 항목")
            ]
        gen = ReportGenerator()
        html = gen.render(report)
        for name in cat_names:
            assert name in html

    def test_short_overview_limit(self) -> None:
        long_text = "가" * 200
        item = TourItem(
            content_id="1", content_type_id=12,
            title="테스트", overview=long_text,
        )
        assert len(item.short_overview) <= 103  # 100자 + "..."
        assert item.short_overview.endswith("...")
