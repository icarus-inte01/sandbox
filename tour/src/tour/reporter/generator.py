"""HTML 리포트 생성기 — TourReport 데이터 → 이메일 호환 HTML."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.tour.models import TourReport


class ReportGenerator:
    """TourReport 데이터를 HTML 리포트로 변환."""

    def __init__(self, template_dir: str | None = None) -> None:
        if template_dir is None:
            template_dir = os.path.join(
                os.path.dirname(__file__), "templates"
            )
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def render(self, report: TourReport, template_name: str = "report.html.j2") -> str:
        """리포트 데이터를 HTML로 렌더링.

        Args:
            report: TourReport 객체
            template_name: Jinja2 템플릿 파일명

        Returns:
            렌더링된 HTML 문자열
        """
        template = self.env.get_template(template_name)

        # 카테고리별 데이터 구성
        categories_data = []
        for cat_name, items in report.categories.items():
            categories_data.append({
                "name": cat_name,
                "items": items,
            })

        context = {
            "region": report.region,
            "date": report.date,
            "generated_at": report.generated_at,
            "categories": categories_data,
            "year": datetime.now().year,
        }

        html = template.render(context)

        # premailer로 CSS 인라인화 (선택사항)

        return html

    def save_html(self, html: str, output_path: str) -> str:
        """HTML 문자열을 파일로 저장.

        Args:
            html: HTML 문자열
            output_path: 출력 파일 경로

        Returns:
            저장된 파일의 절대 경로
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        abs_path = os.path.abspath(output_path)
        return abs_path
