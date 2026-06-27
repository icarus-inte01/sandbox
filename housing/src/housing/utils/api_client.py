"""공공데이터 OpenAPI 공통 호출 클래스.

data.go.kr의 다양한 OpenAPI에 공통 인터페이스를 제공합니다.
"""
from __future__ import annotations

import time
import logging
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from src.housing.config import Config

logger = logging.getLogger(__name__)


class OdcloudClient:
    """공공데이터포털 API 공통 클라이언트.

    - serviceKey 인증 (query parameter)
    - JSON/XML 응답 자동 파싱 (JSON 우선)
    - Pagination 자동 처리
    - Rate limit 준수 (요청 간 delay)
    - 재시도 로직

    Usage:
        client = OdcloudClient()
        data = client.fetch_all("https://api.odcloud.kr/api/...", {"page": 1})
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self._service_key = self.config.data_go_kr_key
        self._last_request_time = 0.0
        self._session = requests.Session()
        # 기본 헤더
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; HousingBot/1.0)",
            "Accept": "application/json, text/plain, */*",
        })

    def _wait_rate_limit(self) -> None:
        """요청 간 최소 간격을 유지합니다."""
        elapsed = time.time() - self._last_request_time
        delay = self.config.request_delay
        if elapsed < delay:
            time.sleep(delay - elapsed)

    def _request(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        method: str = "GET",
    ) -> requests.Response:
        """내부 요청 메서드 (재시도 포함)."""
        if params is None:
            params = {}
        params["serviceKey"] = self._service_key

        self._wait_rate_limit()

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                self._last_request_time = time.time()
                if method == "GET":
                    resp = self._session.get(
                        url, params=params, timeout=self.config.timeout
                    )
                else:
                    resp = self._session.post(
                        url, data=params, timeout=self.config.timeout
                    )
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                last_exc = e
                logger.warning(
                    "API request failed (attempt %d/%d): %s - %s",
                    attempt, self.config.max_retries, url, e,
                )
                if attempt < self.config.max_retries:
                    time.sleep(2 ** attempt)  # exponential backoff
        raise RuntimeError(f"API request failed after {self.config.max_retries} retries: {url}") from last_exc

    def fetch(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """단일 페이지 요청 후 JSON 응답을 반환합니다.

        Returns:
            파싱된 JSON 딕셔너리
        """
        resp = self._request(url, params)
        return resp.json()

    def fetch_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        """단일 페이지 요청 후 XML/텍스트 응답을 반환합니다."""
        resp = self._request(url, params)
        return resp.text

    def fetch_all(
        self,
        base_url: str,
        params: dict[str, Any] | None = None,
        page_param: str = "page",
        per_page_param: str = "perPage",
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        """Pagination을 자동 처리하여 모든 페이지의 데이터를 수집합니다.

        공공데이터 API는 보통 page/perPage 파라미터를 사용합니다.

        Args:
            base_url: API 엔드포인트 URL
            params: 공통 파라미터
            page_param: 페이지 번호 파라미터명 (기본: page)
            per_page_param: 페이지당 건수 파라미터명 (기본: perPage)
            max_pages: 최대 페이지 수 (기본: 10)

        Returns:
            모든 페이지의 데이터 리스트
        """
        if params is None:
            params = {}
        params[per_page_param] = params.get(per_page_param, self.config.per_page)

        all_data: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            params[page_param] = page
            try:
                result = self.fetch(base_url, dict(params))
            except Exception:
                logger.exception("Failed to fetch page %d", page)
                break

            # 응답 구조에 따라 데이터 추출
            data = self._extract_data(result)
            if not data:
                break

            all_data.extend(data)
            logger.info(
                "Fetched page %d: %d items (total: %d)",
                page, len(data), len(all_data),
            )

            # 마지막 페이지 체크
            total_count = self._get_total_count(result)
            if total_count and len(all_data) >= total_count:
                break

        return all_data

    def _extract_data(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """API 응답에서 데이터 리스트를 추출합니다.

        공공데이터 API의 다양한 응답 구조를 처리합니다:
        - {"data": [...]}
        - {"body": {"items": {"item": [...]}}}
        - {"response": {"body": {"items": {"item": [...]}}}}
        - 그 외 배열 필드
        """
        # 공공데이터포털 표준 응답 (ODCloud)
        if "data" in response and isinstance(response["data"], list):
            return response["data"]

        # 국토부 XML 기반 응답 구조
        body = response.get("response", {}).get("body", {})
        items = body.get("items", {})
        if "item" in items:
            item = items["item"]
            if isinstance(item, list):
                return item
            if isinstance(item, dict):
                return [item]

        # LH 등 다른 구조
        if "body" in response:
            items = response["body"].get("items", {})
            if isinstance(items, list):
                return items
            if isinstance(items, dict):
                item = items.get("item", [])
                if isinstance(item, list):
                    return item
                if isinstance(item, dict):
                    return [item]

        # 배열 최상위 응답
        for key, value in response.items():
            if isinstance(value, list) and key != "header":
                return value

        return []

    def _get_total_count(self, response: dict[str, Any]) -> Optional[int]:
        """응답에서 전체 결과 수를 추출합니다."""
        # ODCloud 형식
        if "totalCount" in response:
            return int(response["totalCount"])
        # 국토부 형식
        body = response.get("response", {}).get("body", {})
        if "totalCount" in body:
            return int(body["totalCount"])
        if "numOfRows" in body and "pageNo" in body:
            # 실제 totalCount가 없으면 None
            return None
        return None

    def close(self) -> None:
        self._session.close()
