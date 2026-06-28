"""분양가 할인율 계산 엔진.

분양가와 실거래가를 비교하여 할인율(%)을 계산하고,
할인율을 0-100 점수로 변환합니다.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.housing.models import SaleListing

logger = logging.getLogger(__name__)


def calculate_discount_rate(
    supply_price: int,
    market_avg_price: int,
) -> Optional[float]:
    """분양가 대비 시세 할인율을 계산합니다.

    할인율 = (시세 - 분양가) / 시세 * 100

    Args:
        supply_price: 분양가 (만원)
        market_avg_price: 인근 지역 유사 면적 실거래가 평균 (만원)

    Returns:
        할인율 (%) 또는 None (데이터 부족)
    """
    if supply_price <= 0 or market_avg_price <= 0:
        return None

    discount = (market_avg_price - supply_price) / market_avg_price * 100.0
    return round(discount, 1)


def calculate_discount_rate_per_area(
    supply_price_per_m2: float,
    market_price_per_m2: float,
) -> Optional[float]:
    """㎡당 단가 기준 할인율을 계산합니다.

    할인율 = (주변평단가 - 평당분양가) / 주변평단가 * 100
    총액 대신 ㎡당 단가로 비교하여 면적 차이를 보정합니다.

    Args:
        supply_price_per_m2: 분양단지 ㎡당 분양가 (만원)
        market_price_per_m2: 인근 지역 ㎡당 실거래가 평균 (만원)

    Returns:
        할인율 (%) 또는 None (데이터 부족)
    """
    if supply_price_per_m2 <= 0 or market_price_per_m2 <= 0:
        return None

    discount = (market_price_per_m2 - supply_price_per_m2) / market_price_per_m2 * 100.0
    return round(discount, 1)


def score_from_discount(rate: Optional[float]) -> float:
    """할인율을 0-100 점수로 변환합니다.

    변환 기준:
      - 할인율 20% 이상: 100점 (매우 유리)
      - 할인율 10%: 75점 (유리)
      - 할인율 0%: 50점 (보통, 분양가=시세)
      - 할인율 -10% (분양가 > 시세): 25점 (불리)
      - 할인율 -20% 이하: 0점 (매우 불리)
      - 데이터 없음: 50점 (중립)

    Args:
        rate: 할인율 (%) 또는 None

    Returns:
        0-100 점수
    """
    if rate is None:
        return 50.0

    if rate >= 20.0:
        return 100.0
    if rate >= 10.0:
        # 10~20%: 선형 보간 (75~100)
        return 75.0 + (rate - 10.0) / 10.0 * 25.0
    if rate >= 0.0:
        # 0~10%: 선형 보간 (50~75)
        return 50.0 + rate / 10.0 * 25.0
    if rate >= -10.0:
        # -10~0%: 선형 보간 (25~50)
        return 50.0 + rate / 10.0 * 25.0  # rate가 음수이므로 감소
    if rate >= -20.0:
        # -20~-10%: 선형 보간 (0~25)
        return 25.0 + (rate + 20.0) / 10.0 * 25.0

    return 0.0


def calculate_discount_on_listing(
    listing: SaleListing,
    nearby_prices: dict,
) -> tuple[Optional[float], float]:
    """SaleListing 객체에 대해 할인율과 점수를 계산합니다.

    Args:
        listing: 분양 매물
        nearby_prices: get_nearby_prices() 결과 딕셔너리

    Returns:
        (discount_rate, score) 튜플
    """
    avg_price = nearby_prices.get("avg_price", 0)
    rate = calculate_discount_rate(listing.price, int(avg_price))
    score = score_from_discount(rate)
    return rate, score


def estimate_market_price(
    listing: SaleListing,
    all_nearby_prices: dict[str, dict],
) -> tuple[Optional[float], float]:
    """분양 매물의 예상 시세를 추정하고 할인율을 계산합니다.

    Args:
        listing: 분양 매물
        all_nearby_prices: 지역코드 → nearby_prices 맵

    Returns:
        (discount_rate, score) 튜플
    """
    region_code = listing.region_code
    if region_code and region_code in all_nearby_prices:
        return calculate_discount_on_listing(listing, all_nearby_prices[region_code])

    # 지역코드가 없으면 region 이름으로 매칭 시도
    for code, prices in all_nearby_prices.items():
        if prices.get("trades"):
            first_trade = prices["trades"][0]
            trade_region = getattr(first_trade, "region_code", "")
            if trade_region and trade_region[:2] == listing.region_code[:2]:
                return calculate_discount_on_listing(listing, prices)

    # 데이터 없음: 중립 점수
    return None, 50.0
