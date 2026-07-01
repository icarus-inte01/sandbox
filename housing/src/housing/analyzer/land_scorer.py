"""토지(대지) 평가 점수 계산기.

온비드 공매 대지 물건에 대해 공시지가·할인율·입지·유찰·면적을
종합하여 0-100점으로 평가합니다.
"""
from __future__ import annotations

import logging
import re
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import requests

from src.housing.analyzer.price_comparator import score_from_discount
from src.housing.analyzer.region_data import get_region_score
from src.housing.config import Config
from src.housing.models import SaleListing

logger = logging.getLogger(__name__)

# 기본 가중치 (토지/대지 평가용, 합계 = 1.0)
DEFAULT_LAND_WEIGHTS: dict[str, float] = {
    "official_price_ratio": 0.30,  # 공시지가 대비 입찰가 비율
    "discount_rate": 0.25,         # 감정가 대비 할인율
    "location": 0.25,              # 입지/위치
    "unsold_count": 0.10,          # 유찰횟수
    "scale": 0.10,                 # 면적 규모
}

# vworld.kr 개별공시지가 API (국토교통부 국가공간정보센터)
LAND_PRICE_API_URL = "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"


class LandPriceFetcher:
    """개별공시지가 조회 서비스.

    data.go.kr 국토교통부 API를 통해 PNU(19자리) 기반
    ㎡당 개별공시지가를 조회합니다.
    """

    def __init__(self, service_key: str, request_delay: float = 0.5):
        self._service_key = service_key
        self._request_delay = request_delay
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; HousingBot/1.0)",
            "Accept": "application/json, text/plain, */*",
        })
        self._cache: dict[str, Optional[int]] = {}
        self._last_request = 0.0

    @staticmethod
    def _normalize_pnu(pnu: str) -> str:
        """PNU를 vworld API 호환 포맷으로 정규화.

        온비드 PNU는 산구분(11번째 자리)이 '0'인 경우가 있는데,
        vworld는 '1'(일반) 또는 '2'(산)을 기대함.
        """
        if len(pnu) >= 19 and pnu[10] == '0':
            return pnu[:10] + '1' + pnu[11:]
        return pnu

    def fetch(self, pnu: str, year: int = 2025) -> Optional[int]:
        """단일 PNU의 개별공시지가를 조회합니다.

        Args:
            pnu: 19자리 PNU 코드
            year: 기준년도 (기본 2025)

        Returns:
            ㎡당 공시지가 (원) 또는 None (조회 실패)
        """
        if not pnu or len(pnu) < 19:
            return None

        pnu = self._normalize_pnu(pnu)
        cache_key = f"{pnu}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        params: dict[str, Any] = {
            "key": self._service_key,
            "domain": "",
            "pnu": pnu,
            "stdrYear": str(year),
            "format": "json",
            "numOfRows": "10",
            "pageNo": "1",
        }

        elapsed = _time.time() - self._last_request
        if elapsed < self._request_delay:
            _time.sleep(self._request_delay - elapsed)

        try:
            self._last_request = _time.time()
            resp = self._session.get(LAND_PRICE_API_URL, params=params, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            price = self._parse_response(result)
            self._cache[cache_key] = price
            return price
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            logger.warning("Land price fetch failed (HTTP %d) for PNU=%s", status, pnu)
            self._cache[cache_key] = None
            return None
        except Exception as exc:
            logger.warning("Land price fetch failed for PNU=%s: %s", pnu, exc)
            self._cache[cache_key] = None
            return None

    def fetch_batch(
        self,
        pnu_list: list[str],
        year: int = 2025,
        max_workers: int = 3,
    ) -> dict[str, Optional[int]]:
        """여러 PNU의 공시지가를 병렬로 조회합니다.

        Args:
            pnu_list: PNU 코드 리스트
            year: 기준년도
            max_workers: 병렬 작업 수 (기본 3)

        Returns:
            {pnu: 공시지가(원/㎡) 또는 None} 맵
        """
        results: dict[str, Optional[int]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.fetch, pnu, year): pnu
                for pnu in pnu_list
            }
            for future in as_completed(futures):
                pnu = futures[future]
                try:
                    results[pnu] = future.result()
                except Exception:
                    results[pnu] = None
        return results

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> Optional[int]:
        """개별공시지가 API JSON 응답을 파싱합니다.

        vworld.kr 응답 구조 (format=json):
            {"indvdLandPrices": {"field": [{"pblntfPclnd": 5000000, ...}]}}
        """
        try:
            # vworld wraps in "response" key
            body = data.get("response", data)
            prices = body.get("indvdLandPrices", {})
            fields = prices.get("field", [])
            if fields and isinstance(fields, list) and len(fields) > 0:
                # field name: pblntfPclnd (공시지가 ㎡당 가격)
                val = fields[0].get("pblntfPclnd")
                if val is not None:
                    return int(val)
        except Exception:
            pass
        return None

    @staticmethod
    def extract_jibun(name: str) -> Optional[tuple[str, str]]:
        """리스팅 이름에서 첫 번째 지번(본번-부번)을 추출."""
        m = re.search(r'(\d+)(?:\s*-\s*(\d+))?', name)
        if m:
            return (m.group(1), m.group(2) or '')
        return None

    @staticmethod
    def reconstruct_pnu(pnu: str, name: str) -> Optional[str]:
        """본번/부번=0000인 PNU를 리스팅 주소의 지번으로 재구성.

        Args:
            pnu: 원본 PNU (19자리)
            name: 리스팅 이름

        Returns:
            재구성된 PNU (19자리) 또는 None
        """
        if len(pnu) < 19 or pnu[11:15] != '0000' or pnu[15:19] != '0000':
            return None
        jibun = LandPriceFetcher.extract_jibun(name)
        if not jibun:
            return None
        bonbun, bubun = jibun
        san = '1' if pnu[10] == '0' else pnu[10]
        return pnu[:10] + san + bonbun.zfill(4)[:4] + bubun.zfill(4)[:4]

    @staticmethod
    def estimate_price_from_appraisal(
        appraisal_value: int, area_m2: int,
    ) -> Optional[int]:
        """감정평가액으로 공시지가(㎡당)를 추정.

        감정평가액 × 공시지가현실화율(70%) / 면적으로 추정.
        현실화율은 국토부 통계 기반 기본값 0.7 사용.

        Args:
            appraisal_value: 감정평가액 (원)
            area_m2: 토지 면적 (㎡)

        Returns:
            추정 ㎡당 공시지가 (원) 또는 None
        """
        if appraisal_value <= 0 or area_m2 <= 0:
            return None
        return int(appraisal_value / area_m2 * 0.7)

    def close(self) -> None:
        self._session.close()


# ============================================================
# Scoring functions
# ============================================================

def score_land_discount(apsl_evl_amt: int, min_bid_price_won: int) -> float:
    """감정평가액 대비 최저입찰가 할인율 점수 (0-100).

    할인율 = (감정가 - 입찰가) / 감정가 × 100
    price_comparator.score_from_discount() 로직을 재사용합니다.

    Args:
        apsl_evl_amt: 감정평가액 (원)
        min_bid_price_won: 최저입찰가 (원)

    Returns:
        0-100 점수
    """
    if apsl_evl_amt <= 0 or min_bid_price_won <= 0:
        return 50.0
    discount = (apsl_evl_amt - min_bid_price_won) / apsl_evl_amt * 100.0
    return score_from_discount(discount)


def score_official_price_ratio(
    min_bid_price_won: int,
    official_price_per_m2: Optional[int],
    area_m2: int,
) -> float:
    """공시지가 대비 입찰가 비율 점수 (0-100).

    ratio = 최저입찰가총액 / (공시지가원/㎡ × 면적㎡)
    ratio가 낮을수록 공시지가보다 싸게 사는 것 → 높은 점수

    기준:
      ratio ≤ 0.3 (30%): 100점   — 공시지가보다 70% 싸게
      ratio ≤ 0.5 (50%): 85점
      ratio ≤ 0.8 (80%): 65점
      ratio ≤ 1.0 (100%): 50점   — 공시지가 수준
      ratio ≤ 1.5 (150%): 25점
      ratio ≤ 2.0 (200%): 10점
      ratio > 2.0: 5점

    Args:
        min_bid_price_won: 최저입찰가 총액 (원)
        official_price_per_m2: ㎡당 공시지가 (원) 또는 None
        area_m2: 토지 면적 (㎡)

    Returns:
        0-100 점수 (데이터 없음 = 50점 중립)
    """
    if official_price_per_m2 is None or official_price_per_m2 <= 0:
        return 50.0
    if area_m2 <= 0 or min_bid_price_won <= 0:
        return 50.0

    total_official = official_price_per_m2 * area_m2
    ratio = min_bid_price_won / total_official

    if ratio <= 0.3:
        return 100.0
    if ratio <= 0.5:
        return round(100.0 - (ratio - 0.3) / 0.2 * 15.0, 1)
    if ratio <= 0.8:
        return round(85.0 - (ratio - 0.5) / 0.3 * 20.0, 1)
    if ratio <= 1.0:
        return round(65.0 - (ratio - 0.8) / 0.2 * 15.0, 1)
    if ratio <= 1.5:
        return round(50.0 - (ratio - 1.0) / 0.5 * 25.0, 1)
    if ratio <= 2.0:
        return round(25.0 - (ratio - 1.5) / 0.5 * 15.0, 1)

    return 5.0


def score_land_unsold_count(usbd_nft: int) -> float:
    """유찰횟수 점수 (0-100).

    - 0회: 40점 (경쟁 예상, 인기 물건)
    - 1회: 60점 (적당한 기회)
    - 2회: 80점 (기회 증가)
    - 3회: 90점 (최적 기회)
    - 4~5회: 70점 (유찰 과다 — 상품성 의문)
    - 6회+: 40점

    Args:
        usbd_nft: 유찰횟수

    Returns:
        0-100 점수
    """
    if usbd_nft <= 0:
        return 40.0
    if usbd_nft == 1:
        return 60.0
    if usbd_nft == 2:
        return 80.0
    if usbd_nft == 3:
        return 90.0
    if usbd_nft <= 5:
        return 70.0
    return 40.0


def score_land_scale(area_m2: int) -> float:
    """토지 면적 규모 점수 (0-100).

    기준:
      ≤30㎡: 30점  (소규모, 개발여지 제한)
      ~100㎡: 30→50점
      ~300㎡: 50→80점  (적정 규모)
      ~1000㎡: 80→95점 (최적 — 단독주택/소규모 개발)
      ~3000㎡: 95→65점 (대규모, 자금 부담)
      >3000㎡: 40점

    Args:
        area_m2: 토지 면적 (㎡)

    Returns:
        0-100 점수
    """
    if area_m2 <= 0:
        return 50.0

    if area_m2 <= 30:
        return 30.0
    if area_m2 <= 100:
        return round(30.0 + (area_m2 - 30) / 70.0 * 20.0, 1)
    if area_m2 <= 300:
        return round(50.0 + (area_m2 - 100) / 200.0 * 30.0, 1)
    if area_m2 <= 1000:
        return round(80.0 + (area_m2 - 300) / 700.0 * 15.0, 1)
    if area_m2 <= 3000:
        return round(95.0 - (area_m2 - 1000) / 2000.0 * 30.0, 1)
    return 40.0


def score_land_location(region: str, overrides: Optional[dict[str, float]] = None) -> float:
    """토지 입지 점수 (0-100).  기존 get_region_score()를 재사용합니다."""
    return get_region_score(region, overrides)


# ============================================================
# Main entry points
# ============================================================

def calculate_land_score(
    listing: SaleListing,
    weights: Optional[dict[str, float]] = None,
    region_overrides: Optional[dict[str, float]] = None,
    official_price: Optional[int] = None,
) -> float:
    """단일 토지 매물의 종합 점수를 계산합니다.

    각 항목 점수를 계산하고 가중 평균한 결과를
    listing.total_score 에 저장합니다.

    Args:
        listing: 토지 매물
        weights: 가중치 맵 (None = 기본값)
        region_overrides: 지역 점수 오버라이드
        official_price: ㎡당 공시지가 (원), None이면 공시지가 항목 제외

    Returns:
        0-100 종합 점수
    """
    if weights is None:
        weights = DEFAULT_LAND_WEIGHTS

    min_bid_price_won = listing.price * 10000
    appraisal = listing.raw_data.get("appraisal_value", 0)
    usbd_nft = listing.raw_data.get("usbd_nft", 0)
    area_m2 = listing.units

    discount_score = score_land_discount(appraisal, min_bid_price_won)
    price_ratio_score = score_official_price_ratio(
        min_bid_price_won, official_price, area_m2,
    )
    location_score = score_land_location(listing.region, region_overrides)
    unsold_score = score_land_unsold_count(usbd_nft)
    scale_score = score_land_scale(area_m2)

    # discount_rate, transit_score, scale_score 필드 재사용
    discount_rate_val: Optional[float] = None
    if appraisal > 0 and min_bid_price_won > 0:
        discount_rate_val = round(
            (appraisal - min_bid_price_won) / appraisal * 100.0, 1,
        )
    listing.discount_rate = discount_rate_val
    listing.transit_score = location_score
    listing.scale_score = scale_score
    listing.raw_data["land_scores"] = {
        "price_ratio": round(price_ratio_score, 1),
        "discount": round(discount_score, 1),
        "location": round(location_score, 1),
        "unsold": round(unsold_score, 1),
        "scale": round(scale_score, 1),
    }

    total = (
        (price_ratio_score * weights.get("official_price_ratio", 0.30))
        + (discount_score * weights.get("discount_rate", 0.25))
        + (location_score * weights.get("location", 0.25))
        + (unsold_score * weights.get("unsold_count", 0.10))
        + (scale_score * weights.get("scale", 0.10))
    )

    total = round(total, 1)
    listing.total_score = total

    logger.debug(
        "Land score [%s]: ratio=%.1f discount=%.1f loc=%.1f "
        "unsold=%.1f scale=%.1f total=%.1f",
        listing.name,
        price_ratio_score, discount_score, location_score,
        unsold_score, scale_score, total,
    )

    return total


def calculate_land_scores_batch(
    listings: list[SaleListing],
    config: Optional[Any] = None,
) -> list[SaleListing]:
    """여러 토지 매물의 점수를 일괄 계산합니다.

    1. 중복 PNU 제거 후 공시지가 API 병렬 조회
    2. 각 매물별 종합 점수 계산
    3. listing.total_score 에 저장

    Args:
        listings: 토지 매물 리스트
        config: Config 객체 (None = 기본 설정)

    Returns:
        점수가 계산된 SaleListing 리스트
    """
    if config is None:
        config = Config()

    raw_land_weights = config.get("land_weights", {})
    weights = raw_land_weights if raw_land_weights else DEFAULT_LAND_WEIGHTS
    region_overrides = config.region_score_overrides
    service_key = config.vworld_api_key

    # 중복 제거된 PNU 리스트
    pnu_list = sorted({
        listing.raw_data.get("pnu", "")
        for listing in listings
        if listing.raw_data.get("pnu")
    })

    # 공시지가 조회 (vworld.kr)
    official_prices: dict[str, Optional[int]] = {}
    fetcher: Optional[LandPriceFetcher] = None
    if service_key and not service_key.startswith("${"):
        fetcher = LandPriceFetcher(service_key, config.request_delay)
        try:
            official_prices = fetcher.fetch_batch(pnu_list)
            n_ok = sum(1 for v in official_prices.values() if v is not None)
            logger.info(
                "Land price fetched: %d/%d OK", n_ok, len(official_prices),
            )

            # 2차 시도: 본번/부번=0000 PNU를 리스팅 주소 지번으로 재구성
            pnu_to_listing = {}
            for listing in listings:
                pnu = listing.raw_data.get("pnu", "")
                if pnu and official_prices.get(pnu) is None and pnu not in pnu_to_listing:
                    pnu_to_listing[pnu] = listing

            reconstructed = {}
            for pnu, listing in pnu_to_listing.items():
                new_pnu = LandPriceFetcher.reconstruct_pnu(pnu, listing.name or "")
                if new_pnu and new_pnu != pnu:
                    reconstructed[pnu] = new_pnu

            if reconstructed:
                recon_prices = fetcher.fetch_batch(list(reconstructed.values()))
                for orig_pnu, recon_pnu in reconstructed.items():
                    price = recon_prices.get(recon_pnu)
                    if price is not None and price > 0:
                        official_prices[orig_pnu] = price
                n_recon = sum(
                    1 for p in reconstructed if official_prices.get(p) is not None
                )
                logger.info(
                    "Land price reconstructed: %d/%d OK", n_recon, len(reconstructed),
                )

            # 3차 시도: 감정평가액 기반 추정
            for pnu, listing in pnu_to_listing.items():
                if official_prices.get(pnu) is not None:
                    continue
                appraisal = listing.raw_data.get("appraisal_value", 0) or 0
                area = listing.units or 0
                estimated = LandPriceFetcher.estimate_price_from_appraisal(
                    int(appraisal), int(area),
                )
                if estimated is not None:
                    official_prices[pnu] = estimated
                    logger.info(
                        "Estimated from appraisal for PNU=%s: %d원/㎡",
                        pnu, estimated,
                    )

            n_total = sum(1 for v in official_prices.values() if v is not None)
            logger.info(
                "Land price final: %d/%d OK", n_total, len(official_prices),
            )
        except Exception as exc:
            logger.error("Land price batch fetch failed: %s", exc)
        finally:
            fetcher.close()
    else:
        logger.warning(
            "VWORLD_API_KEY not set — 공시지가 항목 50점(중립) 처리",
        )

    for listing in listings:
        pnu = listing.raw_data.get("pnu", "")
        op = official_prices.get(pnu) if pnu else None
        calculate_land_score(listing, weights, region_overrides, op)

    return listings
