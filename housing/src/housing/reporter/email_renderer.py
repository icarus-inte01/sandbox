"""HTML 이메일 렌더러.

Jinja2 템플릿을 사용하여 유망도 리포트 HTML을 생성합니다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from src.housing.models import SaleListing

logger = logging.getLogger(__name__)

# 템플릿 디렉토리
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Jinja2 환경
_env: Optional[Environment] = None


def _get_env() -> Environment:
    """Jinja2 환경을 지연 초기화합니다."""
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True,
        )
        # Jinja2 필터 등록
        _env.filters["score_color"] = _score_color
        _env.filters["krw_format"] = _krw_format
        _env.filters["status_kr"] = _status_kr
        _env.filters["supply_type_kr"] = _supply_type_kr
    return _env


def _score_color(score: Optional[float]) -> str:
    """점수에 따른 색상 코드 반환."""
    if score is None:
        return "#999999"
    if score >= 80:
        return "#1a7a3a"  # 짙은 녹색
    if score >= 70:
        return "#2d8f4e"  # 녹색
    if score >= 60:
        return "#e6a817"  # 노란색
    return "#b91c1c"  # 빨간색


def _krw_format(value: Optional[int]) -> str:
    """만원 단위 금액을 억/만원 포맷으로 변환."""
    if value is None:
        return "-"
    if value >= 10000:
        return f"{value // 10000}억{value % 10000:,}만원"
    return f"{value:,}만원"


def _status_kr(status) -> str:
    """분양상태 → 한글 변환."""
    mapping = {
        "planned": "분양예정",
        "open": "청약중",
        "closed": "청약마감",
        "unsold": "미분양",
    }
    return mapping.get(status.value if hasattr(status, 'value') else str(status), str(status))


def _supply_type_kr(supply_type) -> str:
    """분양유형 → 한글 변환."""
    mapping = {
        "apt": "아파트",
        "public": "공공분양",
        "land": "택지",
        "sh": "SH분양",
        "officetel": "오피스텔",
        "other": "기타",
    }
    return mapping.get(supply_type.value if hasattr(supply_type, 'value') else str(supply_type), str(supply_type))


def render_report(
    listings: list[SaleListing],
    report_date: str,
    title: str = "분양정보 유망도 리포트",
    include_notes: bool = True,
) -> str:
    """유망도 리포트 HTML을 렌더링합니다.

    Args:
        listings: 분양정보 리스트 (total_score 내림차순 정렬 권장)
        report_date: 보고서 일자 문자열
        title: 제목
        include_notes: 면책 문구 포함 여부

    Returns:
        렌더링된 HTML 문자열
    """
    env = _get_env()
    template = env.get_template("report.html")

    scored_listings = []
    for listing in listings:
        units_table = []
        avg_price_per_pyung = 0
        avg_weight = 0
        if listing.units_info:
            for u in listing.units_info:
                price = u.get("price", 0) or 0
                area = u.get("supply_area", "") or ""
                hh = u.get("households", 0) or 0
                ppy = u.get("price_per_pyung", 0) or 0
                price_str = _krw_format(price) if price > 0 else "정보없음"
                units_table.append({
                    "house_type": u.get("house_type", ""),
                    "supply_area": area,
                    "price_str": price_str,
                    "price_per_pyung": int(ppy) if ppy > 0 else 0,
                    "households": hh,
                })
                if ppy and ppy > 0 and hh > 0:
                    avg_price_per_pyung += ppy * hh
                    avg_weight += hh

        market_price_per_m2 = getattr(listing, "market_price_per_m2", 0) or 0
        market_price_per_pyung = round(market_price_per_m2 * 3.3058) if market_price_per_m2 > 0 else 0
        if market_price_per_pyung > 0:
            market_price_str = f"평당 {market_price_per_pyung:,}만원"
        else:
            market_price_str = "-"

        d = {
            "name": listing.name,
            "region": listing.region,
            "supply_type": listing.supply_type,
            "supply_type_kr": _supply_type_kr(listing.supply_type),
            "status": listing.status,
            "status_kr": _status_kr(listing.status),
            "units": listing.units,
            "builder": listing.builder or "-",
            "discount_rate": listing.discount_rate,
            "market_price_per_pyung": market_price_per_pyung,
            "market_price_str": market_price_str,
            "total_score": listing.total_score,
            "score_color": _score_color(listing.total_score),
            "source": listing.source,
            "competition_rate": listing.competition_rate if listing.competition_rate else None,
            "transit_score": listing.transit_score,
            "brand_score": listing.brand_score,
            "competition_score": listing.competition_score,
            "scale_score": listing.scale_score,
            "avg_price_per_pyung": round(avg_price_per_pyung / avg_weight) if avg_weight > 0 else 0,
            "units_table": units_table,
            "has_breakdown": any([
                listing.transit_score is not None,
                listing.brand_score is not None,
                listing.competition_score is not None,
                listing.scale_score is not None,
            ]),
        }
        scored_listings.append(d)

    html = template.render(
        title=title,
        report_date=report_date,
        listings=scored_listings,
        total_count=len(scored_listings),
        include_notes=include_notes,
    )
    return html
