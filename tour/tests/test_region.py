"""지역 매퍼 테스트."""
from __future__ import annotations

import pytest

from src.tour.region import get_region_list, resolve_region


class TestResolveRegion:
    """resolve_region() 함수 테스트."""

    def test_resolve_seoul(self) -> None:
        assert resolve_region("서울") == 1

    def test_resolve_busan(self) -> None:
        assert resolve_region("부산") == 6

    def test_resolve_jeju(self) -> None:
        assert resolve_region("제주") == 39

    def test_resolve_with_full_name(self) -> None:
        assert resolve_region("서울특별시") == 1
        assert resolve_region("부산광역시") == 6
        assert resolve_region("제주특별자치도") == 39

    def test_resolve_english(self) -> None:
        assert resolve_region("seoul") == 1
        assert resolve_region("busan") == 6
        assert resolve_region("jeju") == 39

    def test_resolve_whitespace(self) -> None:
        assert resolve_region("  서울  ") == 1

    def test_resolve_case_insensitive(self) -> None:
        assert resolve_region("Seoul") == 1
        assert resolve_region("BUSAN") == 6

    def test_resolve_invalid_region(self) -> None:
        with pytest.raises(ValueError, match="지원하지 않는 지역"):
            resolve_region("없는지역")

    def test_resolve_empty_string(self) -> None:
        with pytest.raises(ValueError):
            resolve_region("")


class TestGetRegionList:
    """get_region_list() 함수 테스트."""

    def test_contains_major_regions(self) -> None:
        regions = get_region_list()
        assert "서울" in regions
        assert "부산" in regions
        assert "제주" in regions
        assert len(regions) == 17  # 광역시/도 17개

    def test_no_duplicates(self) -> None:
        regions = get_region_list()
        assert len(regions) == len(set(regions))
