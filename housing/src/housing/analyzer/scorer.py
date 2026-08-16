"""종합 유망도 점수 계산기.

4가지 항목의 가중치를 적용한 종합 점수를 계산합니다.
(청약경쟁률은 실데이터 미수집으로 제거됨)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.housing.analyzer.brand_scores import get_brand_score
from src.housing.analyzer.price_comparator import score_from_discount
from src.housing.analyzer.region_data import REGION_CODE_MAP, get_region_score
from src.housing.config import Config
from src.housing.models import SaleListing

logger = logging.getLogger(__name__)


# 기본 가중치 (config.yaml에서 오버라이드 가능) — 합계 = 1.0
DEFAULT_WEIGHTS = {
    "discount_rate": 0.41,
    "transit_location": 0.35,
    "brand": 0.18,
    "scale": 0.06,
}


def calculate_score(
    listing: SaleListing,
    weights: Optional[dict[str, float]] = None,
    brand_overrides: Optional[dict[str, float]] = None,
    region_overrides: Optional[dict[str, float]] = None,
) -> float:
    """단일 매물의 종합 유망도 점수를 계산합니다.

    각 항목별 점수에 가중치를 곱하여 합산합니다.

    Args:
        listing: 분양 매물
        weights: 가중치 맵 (None=기본값)
        brand_overrides: 브랜드 점수 오버라이드
        region_overrides: 지역 점수 오버라이드

    Returns:
        0-100 종합 점수
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    # 각 항목 점수 계산
    discount_score = _get_discount_score(listing)
    transit_score = _get_transit_score(listing, region_overrides)
    brand_score = _get_brand_score(listing, brand_overrides)
    scale_score = _get_scale_score(listing)

    # 점수를 listing에 저장 (추후 리포트용)
    listing.discount_rate = getattr(listing, 'discount_rate', None)
    listing.transit_score = transit_score
    listing.brand_score = brand_score
    listing.scale_score = scale_score

    # 가중 평균
    total = (
        (discount_score * weights.get("discount_rate", 0.41)) +
        (transit_score * weights.get("transit_location", 0.35)) +
        (brand_score * weights.get("brand", 0.18)) +
        (scale_score * weights.get("scale", 0.06))
    )

    total = round(total, 1)
    listing.total_score = total

    return total


def calculate_scores_batch(
    listings: list[SaleListing],
    config: Optional[Any] = None,
) -> list[SaleListing]:
    """여러 매물의 점수를 일괄 계산합니다.

    Args:
        listings: 분양 매물 리스트
        config: Config 객체 (None=기본 설정 사용)

    Returns:
        점수가 계산된 SaleListing 리스트
    """
    if config is None:
        config = Config()

    weights = dict(config.weights) if config.weights else DEFAULT_WEIGHTS
    brand_overrides = config.brand_score_overrides
    region_overrides = config.region_score_overrides

    for listing in listings:
        calculate_score(listing, weights, brand_overrides, region_overrides)

    return listings


def _get_discount_score(listing: SaleListing) -> float:
    """분양가 할인율 점수 (weight 0.41).

    discount_rate가 이미 계산되어 있으면 사용하고,
    없으면 중립 점수(50)를 반환합니다.
    """
    if listing.discount_rate is not None:
        return score_from_discount(listing.discount_rate)
    return 50.0


def _get_transit_score(listing: SaleListing, overrides: Optional[dict[str, float]] = None) -> float:
    """교통/입지 점수 (weight 0.35).

    region_code(청약홈 3자리)가 있으면 코드 → 시/도 이름으로 정확히 조회하고,
    없으면(LH/onbid) 주소 문자열 파싱으로 fallback합니다.
    """
    sido = REGION_CODE_MAP.get(listing.region_code or "", "")
    if sido:
        return get_region_score(sido, overrides)
    return get_region_score(listing.region, overrides)


def _get_brand_score(listing: SaleListing, overrides: Optional[dict[str, float]] = None) -> float:
    """시공사 브랜드 점수 (weight 0.18).

    builder 필드의 시공사명으로 브랜드 점수를 조회합니다.
    """
    if not listing.builder:
        return 50.0
    return get_brand_score(listing.builder, overrides)


def _get_scale_score(listing: SaleListing) -> float:
    """공급규모 점수 (weight 0.06).

    세대수 기반 점수:
    - 1000세대 이상: 100점
    - 500세대: 50점
    - 100세대: 10점
    - 선형 보간
    """
    units = listing.units
    if units >= 1000:
        return 100.0
    if units >= 100:
        return units / 1000.0 * 100.0
    return units / 100.0 * 10.0
