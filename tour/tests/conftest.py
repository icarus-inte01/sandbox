"""pytest fixtures — 공통 테스트 데이터 및 Mock 객체."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.tour.models import TourItem


@pytest.fixture
def sample_tour_item() -> TourItem:
    """기본 TourItem fixture."""
    return TourItem(
        content_id="126508",
        content_type_id=12,
        title="경복궁",
        addr1="서울특별시 종로구 사직로 161",
        tel="02-3700-3900",
        first_image="http://example.com/image.jpg",
        overview="조선시대 대표 궁궐입니다.",
        map_x=126.9765,
        map_y=37.5796,
        area_code=1,
    )


@pytest.fixture
def sample_api_response() -> dict:
    """TourAPI areaBasedList1 응답 모방."""
    return {
        "response": {
            "header": {"resultCode": "0000", "resultMsg": "OK"},
            "body": {
                "numOfRows": 10,
                "pageNo": 1,
                "totalCount": 2,
                "items": {
                    "item": [
                        {
                            "contentid": "126508",
                            "contenttypeid": "12",
                            "title": "경복궁",
                            "addr1": "서울특별시 종로구 사직로 161",
                            "addr2": "",
                            "firstimage": "http://example.com/1.jpg",
                            "mapx": "126.9765",
                            "mapy": "37.5796",
                            "areacode": "1",
                            "sigungucode": "1",
                            "createdtime": "20050101000000",
                            "modifiedtime": "20240101000000",
                        },
                        {
                            "contentid": "132456",
                            "contenttypeid": "12",
                            "title": "북촌한옥마을",
                            "addr1": "서울특별시 종로구 계동길 37",
                            "addr2": "",
                            "firstimage": "",
                            "mapx": "126.9864",
                            "mapy": "37.5826",
                            "areacode": "1",
                            "sigungucode": "1",
                        },
                    ]
                },
            },
        }
    }


@pytest.fixture
def sample_festival_response() -> dict:
    """TourAPI searchFestival1 응답 모방."""
    return {
        "response": {
            "header": {"resultCode": "0000", "resultMsg": "OK"},
            "body": {
                "numOfRows": 10,
                "pageNo": 1,
                "totalCount": 1,
                "items": {
                    "item": [
                        {
                            "contentid": "2674675",
                            "contenttypeid": "15",
                            "title": "수원화성의 비밀",
                            "addr1": "경기도 수원시 팔달구 행궁로 11",
                            "firstimage": "",
                            "mapx": "127.0152",
                            "mapy": "37.2810",
                            "areacode": "31",
                            "eventstartdate": "20260101",
                            "eventenddate": "20261231",
                        },
                    ]
                },
            },
        }
    }


@pytest.fixture
def mock_api_client() -> MagicMock:
    """Mock된 TourAPIClient."""
    client = MagicMock()
    client.fetch_by_region.return_value = [
        {
            "contentid": "126508",
            "contenttypeid": "12",
            "title": "경복궁",
            "addr1": "서울특별시 종로구 사직로 161",
        },
    ]
    client.fetch_festivals.return_value = [
        {
            "contentid": "2674675",
            "contenttypeid": "15",
            "title": "수원화성의 비밀",
            "addr1": "경기도 수원시 팔달구 행궁로 11",
            "eventstartdate": "20260101",
            "eventenddate": "20261231",
        },
    ]
    client.fetch_detail.return_value = {
        "overview": "상세 설명입니다.",
        "homepage": "http://example.com",
    }
    return client


@pytest.fixture
def tmp_cache_dir(tmp_path) -> str:
    """임시 캐시 디렉토리."""
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    return str(cache_dir)
