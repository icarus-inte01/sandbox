"""지역/교통 점수 테스트."""
from __future__ import annotations

from src.housing.analyzer.region_data import REGION_SCORES, address_to_dong_name, get_region_score


class TestRegionScores:
    def test_region_count(self):
        """지역 50개 이상."""
        assert len(REGION_SCORES) >= 50, f"Only {len(REGION_SCORES)} regions"

    def test_seoul_top_score(self):
        """서울 최상위 점수."""
        score = get_region_score("서울특별시")
        assert score >= 90

    def test_subway_bonus(self):
        """강남구 역세권 가산점."""
        score = get_region_score("서울특별시 강남구")
        assert score > get_region_score("서울특별시")
        assert score <= 100

    def test_rural_lower_score(self):
        """지방 도시 낮은 점수."""
        big_city = get_region_score("서울특별시")
        rural = get_region_score("강원도")
        assert rural < big_city

    def test_unknown_default(self):
        """알 수 없는 지역 기본 50점."""
        score = get_region_score("존재하지않는지역")
        assert score == 50.0

    def test_overrides(self):
        """오버라이드 적용."""
        overrides = {"서울특별시": 50.0}
        score = get_region_score("서울특별시", overrides)
        assert score == 50.0


class TestDongNameExtraction:
    def test_dong(self):
        """일반 동 주소."""
        assert address_to_dong_name("서울특별시 영등포구 신길동 413-8번지 일원") == "신길동"

    def test_eup(self):
        """읍 단위 주소."""
        assert address_to_dong_name("경기도 남양주시 오남읍 양지리 101번지 일원") == "오남읍"

    def test_myeon(self):
        """면 단위 주소."""
        assert address_to_dong_name("경기도 용인시 처인구 원삼면 산업단지 D1-1블록") == "원삼면"

    def test_dong_ga(self):
        """동+가 번호 (우아동3가)."""
        assert address_to_dong_name("전북특별자치도 전주시 덕진구 우아동3가 752-41 일원") == "우아동3가"

    def test_paren_dong(self):
        """괄호 안 동명 (월출동)."""
        assert address_to_dong_name("광주연구개발특구 첨단3지구 A6블록(전남광주통합특별시 북구 월출동)") == "월출동"

    def test_no_dong(self):
        """동명 없는 도로명 주소."""
        assert address_to_dong_name("서울특별시 구로구 오리로1165") == ""

    def test_empty(self):
        """빈 문자열."""
        assert address_to_dong_name("") == ""
        assert address_to_dong_name(None) == ""
