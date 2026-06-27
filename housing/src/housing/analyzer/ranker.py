"""순위화 엔진.

점수에 따라 매물을 정렬하고, 카테고리별로 분류합니다.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.housing.models import SaleListing, SupplyType

logger = logging.getLogger(__name__)


def rank_listings(
    listings: list[SaleListing],
    scores: Optional[dict[str, float]] = None,
) -> list[SaleListing]:
    """매물을 점수 내림차순으로 정렬합니다.

    Args:
        listings: 매물 리스트
        scores: name → total_score 맵 (None이면 listing.total_score 사용)

    Returns:
        점수 내림차순 정렬된 리스트
    """
    def _get_score(listing: SaleListing) -> float:
        if scores and listing.name in scores:
            return scores[listing.name]
        return listing.total_score or 0.0

    return sorted(listings, key=_get_score, reverse=True)


def rank_by_category(
    listings: list[SaleListing],
) -> dict[SupplyType, list[SaleListing]]:
    """매물을 분양유형별로 분류하고 각각 순위화합니다.

    Returns:
        SupplyType → 정렬된 SaleListing 리스트 맵
    """
    categorized: dict[SupplyType, list[SaleListing]] = {}

    for listing in listings:
        st = listing.supply_type
        if st not in categorized:
            categorized[st] = []
        categorized[st].append(listing)

    # 각 카테고리 내 정렬
    for st in categorized:
        categorized[st] = rank_listings(categorized[st])

    return categorized


def top_n(
    listings: list[SaleListing],
    n: int = 10,
    min_score: float = 0.0,
) -> list[SaleListing]:
    """상위 N개 매물을 반환합니다.

    Args:
        listings: 정렬된 매물 리스트
        n: 반환할 개수
        min_score: 최소 점수 필터

    Returns:
        상위 N개 리스트
    """
    ranked = rank_listings(listings)
    filtered = [l for l in ranked if (l.total_score or 0) >= min_score]
    return filtered[:n]


def summarize_ranking(listings: list[SaleListing]) -> str:
    """순위 요약 문자열을 생성합니다."""
    lines = []
    for i, listing in enumerate(rank_listings(listings), 1):
        score = listing.total_score or 0
        lines.append(f"{i:3d}. [{score:5.1f}점] {listing.name} - {listing.region}")
    return "\n".join(lines)
