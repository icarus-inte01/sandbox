"""TourAPI 클라이언트 테스트."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.tour.api import TourAPIClient, TourAPIError
from src.tour.cache import TourCache
from src.tour.config import load_config


@pytest.fixture
def client(tmp_cache_dir: str) -> TourAPIClient:
    """TourAPIClient fixture (실제 HTTP 호출 안함)."""
    config = load_config()
    cache = TourCache(cache_dir=tmp_cache_dir, ttl_days=7)
    return TourAPIClient("test-key", config, cache=cache)


class TestTourAPIClient:
    """TourAPIClient 클래스 테스트."""

    def test_build_url(self, client: TourAPIClient) -> None:
        url = client._build_url("areaBasedList2")
        assert url == "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"

    def test_build_url_custom(self, client: TourAPIClient) -> None:
        url = client._build_url("detailCommon2")
        assert url == "https://apis.data.go.kr/B551011/KorService2/detailCommon2"

    def test_build_default_params(self, client: TourAPIClient) -> None:
        params = client._build_default_params()
        assert params["serviceKey"] == "test-key"
        assert params["MobileOS"] == "ETC"
        assert params["MobileApp"] == "TourReport"
        assert params["_type"] == "json"

    def test_extract_items_normal(self, client: TourAPIClient) -> None:
        response = {
            "response": {
                "body": {
                    "items": {
                        "item": [
                            {"contentid": "1", "title": "A"},
                            {"contentid": "2", "title": "B"},
                        ]
                    }
                }
            }
        }
        items = client._extract_items(response)
        assert len(items) == 2
        assert items[0]["title"] == "A"

    def test_extract_items_empty(self, client: TourAPIClient) -> None:
        response = {
            "response": {
                "body": {
                    "items": {"item": []}
                }
            }
        }
        items = client._extract_items(response)
        assert items == []

    def test_extract_items_none(self, client: TourAPIClient) -> None:
        response = {
            "response": {
                "body": {
                    "items": {"item": None}
                }
            }
        }
        items = client._extract_items(response)
        assert items == []

    def test_extract_items_single_dict(self, client: TourAPIClient) -> None:
        response = {
            "response": {
                "body": {
                    "items": {
                        "item": {"contentid": "1", "title": "Single"}
                    }
                }
            }
        }
        items = client._extract_items(response)
        assert len(items) == 1
        assert items[0]["title"] == "Single"

    @patch("src.tour.api.requests.Session.get")
    def test_request_success(self, mock_get, client: TourAPIClient) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": {
                "header": {"resultCode": "0000", "resultMsg": "OK"},
                "body": {"items": {"item": []}},
            }
        }
        mock_get.return_value = mock_resp

        result = client._request("areaBasedList1", {"areaCode": "1"})
        assert result["response"]["header"]["resultCode"] == "0000"

    @patch("src.tour.api.requests.Session.get")
    def test_request_api_error(self, mock_get, client: TourAPIClient) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": {
                "header": {"resultCode": "ERROR", "resultMsg": "Invalid key"},
                "body": {"items": {"item": []}},
            }
        }
        mock_get.return_value = mock_resp

        with pytest.raises(TourAPIError, match="TourAPI 오류"):
            client._request("areaBasedList1", {})

    def test_fetch_with_cache(self, client: TourAPIClient) -> None:
        """캐시 저장 후 동일 요청시 캐시 반환."""
        # fetch_by_region이 사용하는 키 형식: "area-{area_code}-type-{content_type_id}-page-{page_no}"
        cache_key = "area-1-type-12-page-1"
        client.cache.set(cache_key, {
            "response": {
                "header": {"resultCode": "0000", "resultMsg": "OK"},
                "body": {
                    "items": {
                        "item": [{"contentid": "1", "title": "Cached"}]
                    }
                }
            }
        })

        # 캐시에 저장된 키가 fetch_by_region 내부에서 확인되어 _request 호출 없이 캐시 반환
        items = client.fetch_by_region(1, 12)
        assert len(items) > 0
        assert items[0]["title"] == "Cached"

    @patch("src.tour.api.requests.Session.get")
    def test_fetch_detail(self, mock_get, client: TourAPIClient) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": {
                "header": {"resultCode": "0000", "resultMsg": "OK"},
                "body": {
                    "items": {
                        "item": [
                            {
                                "contentid": "126508",
                                "title": "경복궁",
                                "overview": "상세 설명",
                                "firstimage": "http://img.jpg",
                            }
                        ]
                    }
                },
            }
        }
        mock_get.return_value = mock_resp

        detail = client.fetch_detail("126508", 12)
        assert detail["title"] == "경복궁"
        assert detail["overview"] == "상세 설명"
