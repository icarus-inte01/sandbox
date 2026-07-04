"""TourAPI 클라이언트 — 한국관광공사 TourAPI 호출 및 응답 처리."""
from __future__ import annotations

import time
from typing import Any

import requests

from src.tour.cache import TourCache
from src.tour.config import Config


class TourAPIError(Exception):
    """TourAPI 호출 중 발생한 에러."""


class TourAPIClient:
    """한국관광공사 TourAPI 클라이언트.

    Attributes:
        api_key: TourAPI 서비스 키
        config: 설정 객체
        cache: 캐시 객체 (선택사항)
    """

    def __init__(
        self,
        api_key: str,
        config: Config,
        cache: TourCache | None = None,
    ) -> None:
        self.api_key = api_key
        self.config = config
        self.cache = cache or TourCache(
            cache_dir=config.get_cache_dir(),
            ttl_days=config.get_cache_ttl_days(),
        )
        self.base_url = config.get_base_url()
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    def _build_url(self, endpoint: str) -> str:
        """API 엔드포인트 URL 생성."""
        return f"{self.base_url}/{endpoint}"

    def _build_default_params(self) -> dict[str, str]:
        """공통 요청 파라미터."""
        return {
            "serviceKey": self.api_key,
            "MobileOS": self.config.get_api_setting("mobile_os", "ETC"),
            "MobileApp": self.config.get_api_setting("mobile_app", "TourReport"),
            "_type": "json",
        }

    def _request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """HTTP GET 요청 수행.

        Args:
            endpoint: API 엔드포인트명
            params: 요청 파라미터

        Returns:
            응답 JSON 데이터

        Raises:
            TourAPIError: API 호출 실패시
        """
        url = self._build_url(endpoint)
        all_params = self._build_default_params()
        all_params.update(params)

        max_retries = self.config.get_api_setting("max_retries", 3)
        timeout = self.config.get_api_setting("timeout", 30)
        delay = self.config.get_api_setting("request_delay", 0.1)

        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    time.sleep(delay * (2 ** attempt))  # exponential backoff

                resp = self._session.get(url, params=all_params, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()

                # TourAPI 응답 헤더 확인
                header = data.get("response", {}).get("header", {})
                result_code = header.get("resultCode", "")
                result_msg = header.get("resultMsg", "")

                if result_code != "0000":
                    raise TourAPIError(
                        f"TourAPI 오류 (endpoint={endpoint}): "
                        f"code={result_code}, msg={result_msg}"
                    )

                return data

            except requests.exceptions.Timeout as e:
                last_error = TourAPIError(f"요청 시간 초과 (endpoint={endpoint}): {e}")
            except requests.exceptions.HTTPError as e:
                last_error = TourAPIError(f"HTTP 오류 (endpoint={endpoint}): {e}")
            except requests.exceptions.ConnectionError as e:
                last_error = TourAPIError(f"연결 오류 (endpoint={endpoint}): {e}")
            except (ValueError, KeyError) as e:
                last_error = TourAPIError(f"응답 파싱 오류 (endpoint={endpoint}): {e}")

            if attempt < max_retries - 1:
                time.sleep(delay)

        raise TourAPIError(
            f"API 호출 실패 ({max_retries}회 재시도 후): {last_error}"
        ) from last_error

    def _extract_items(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """TourAPI 응답에서 items 목록 추출."""
        body = response.get("response", {}).get("body", {})
        items = body.get("items", {})

        # items가 문자열(빈 결과)이거나 None인 경우
        if not isinstance(items, dict):
            return []

        item_list = items.get("item", [])
        if item_list is None:
            return []
        if isinstance(item_list, dict):
            return [item_list]
        return item_list

    def fetch_by_region(
        self,
        area_code: int,
        content_type_id: int,
        arrange: str = "O",
        num_rows: int = 10,
        page_no: int = 1,
    ) -> list[dict[str, Any]]:
        """지역 기반 관광정보 조회 (areaBasedList1).

        Args:
            area_code: 지역 코드
            content_type_id: 콘텐츠 타입 ID
            arrange: 정렬 방식 (O=인기순, B=수정일순)
            num_rows: 페이지당 결과 수
            page_no: 페이지 번호

        Returns:
            관광정보 항목 리스트
        """
        cache_key = f"area-{area_code}-type-{content_type_id}-page-{page_no}"

        # 캐시 확인
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return self._extract_items(cached)

        params = {
            "areaCode": str(area_code),
            "contentTypeId": str(content_type_id),
            "arrange": arrange,
            "numOfRows": str(num_rows),
            "pageNo": str(page_no),
        }

        response = self._request("areaBasedList2", params)

        # 캐시 저장
        if self.cache:
            self.cache.set(cache_key, response)

        return self._extract_items(response)

    def fetch_festivals(
        self,
        area_code: int,
        event_start_date: str,
        num_rows: int = 10,
        page_no: int = 1,
    ) -> list[dict[str, Any]]:
        """행사/축제 정보 조회 (searchFestival1).

        Args:
            area_code: 지역 코드
            event_start_date: 행사 시작일 (YYYYMMDD)
            num_rows: 페이지당 결과 수
            page_no: 페이지 번호

        Returns:
            행사 정보 리스트
        """
        cache_key = f"festival-area-{area_code}-date-{event_start_date}-page-{page_no}"

        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return self._extract_items(cached)

        params = {
            "areaCode": str(area_code),
            "eventStartDate": event_start_date,
            "numOfRows": str(num_rows),
            "pageNo": str(page_no),
        }

        response = self._request("searchFestival2", params)

        if self.cache:
            self.cache.set(cache_key, response)

        return self._extract_items(response)

    def fetch_by_keyword(
        self,
        keyword: str,
        area_code: int | None = None,
        content_type_id: int | None = None,
        num_rows: int = 10,
    ) -> list[dict[str, Any]]:
        """키워드 검색 (searchKeyword1).

        Args:
            keyword: 검색 키워드
            area_code: 지역 코드 (선택)
            content_type_id: 콘텐츠 타입 ID (선택)
            num_rows: 페이지당 결과 수

        Returns:
            검색 결과 리스트
        """
        params: dict[str, Any] = {
            "keyword": keyword,
            "numOfRows": str(num_rows),
            "pageNo": "1",
            "listYN": "Y",
            "arrange": self.config.get_sort_order(),
        }
        if area_code is not None:
            params["areaCode"] = str(area_code)
        if content_type_id is not None:
            params["contentTypeId"] = str(content_type_id)

        response = self._request("searchKeyword2", params)
        return self._extract_items(response)

    def _enrichment_cache_key(self, endpoint: str, content_id: str, type_id: int = 0) -> str:
        return f"enrich-{endpoint}-{content_id}-t{type_id}"

    def fetch_detail(
        self,
        content_id: str,
        content_type_id: int,
    ) -> dict[str, Any]:
        """공통 상세정보 조회 (detailCommon2 - v4.3).

        TourAPI v4.3: contentId만 전송. contentTypeId 및 YN 파라미터 제거됨.
        """
        cache_key = self._enrichment_cache_key("detailCommon2", content_id, content_type_id)
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        params = {"contentId": content_id}
        response = self._request("detailCommon2", params)
        items = self._extract_items(response)
        result = items[0] if items else {}

        if self.cache:
            self.cache.set(cache_key, result)
        return result

    def fetch_intro(
        self,
        content_id: str,
        content_type_id: int,
    ) -> dict[str, Any]:
        """소개정보 조회 (detailIntro2)."""
        cache_key = self._enrichment_cache_key("detailIntro2", content_id, content_type_id)
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        params = {
            "contentId": content_id,
            "contentTypeId": str(content_type_id),
        }
        response = self._request("detailIntro2", params)
        items = self._extract_items(response)
        result = items[0] if items else {}

        if self.cache:
            self.cache.set(cache_key, result)
        return result

    def fetch_info(
        self,
        content_id: str,
        content_type_id: int,
    ) -> list[dict[str, Any]]:
        """추가정보 조회 (detailInfo2)."""
        cache_key = self._enrichment_cache_key("detailInfo2", content_id, content_type_id)
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        params = {
            "contentId": content_id,
            "contentTypeId": str(content_type_id),
        }
        response = self._request("detailInfo2", params)
        result = self._extract_items(response)

        if self.cache:
            self.cache.set(cache_key, result)
        return result

    def fetch_images(
        self,
        content_id: str,
    ) -> list[dict[str, Any]]:
        """이미지정보 조회 (detailImage1).

        Args:
            content_id: 콘텐츠 ID

        Returns:
            이미지 정보 리스트
        """
        params = {
            "contentId": content_id,
            "imageYN": "Y",
            "subImageYN": "Y",
        }

        response = self._request("detailImage2", params)
        return self._extract_items(response)
