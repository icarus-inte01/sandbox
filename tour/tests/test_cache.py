"""캐시 모듈 테스트."""
from __future__ import annotations

import json
import os
import time

import pytest

from src.tour.cache import TourCache


class TestTourCache:
    """TourCache 클래스 테스트."""

    def test_set_and_get(self, tmp_cache_dir: str) -> None:
        cache = TourCache(cache_dir=tmp_cache_dir, ttl_days=7)
        cache.set("test-key", {"data": "hello"})
        result = cache.get("test-key")
        assert result is not None
        assert result["data"] == "hello"

    def test_get_missing(self, tmp_cache_dir: str) -> None:
        cache = TourCache(cache_dir=tmp_cache_dir, ttl_days=7)
        result = cache.get("nonexistent-key")
        assert result is None

    def test_get_expired(self, tmp_cache_dir: str) -> None:
        cache = TourCache(cache_dir=tmp_cache_dir, ttl_days=0)  # 즉시 만료
        cache.set("expire-key", {"data": "x"})
        time.sleep(0.1)  # TTL=0이므로 바로 만료
        result = cache.get("expire-key")
        assert result is None

    def test_clear(self, tmp_cache_dir: str) -> None:
        cache = TourCache(cache_dir=tmp_cache_dir, ttl_days=7)
        cache.set("key1", {"data": "a"})
        cache.set("key2", {"data": "b"})
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_clear_expired(self, tmp_cache_dir: str) -> None:
        cache = TourCache(cache_dir=tmp_cache_dir, ttl_days=7)
        cache.set("valid-key", {"data": "a"})
        # 만료된 캐시 수동 생성
        expired_path = os.path.join(tmp_cache_dir, "expired.json")
        expired_entry = {
            "_meta": {"expires_at": time.time() - 3600},  # 1시간 전 만료
            "data": {"data": "expired"},
        }
        with open(expired_path, "w") as f:
            json.dump(expired_entry, f)

        removed = cache.clear_expired()
        assert removed >= 1
        assert cache.get("valid-key") is not None  # 유효한 캐시는 남아있어야 함

    def test_auto_directory_creation(self, tmp_path) -> None:
        new_dir = os.path.join(str(tmp_path), "new-cache")
        cache = TourCache(cache_dir=new_dir, ttl_days=7)
        cache.set("test-key", {"data": "auto"})
        assert os.path.exists(new_dir)
        assert os.path.exists(os.path.join(new_dir, "test-key.json"))

    def test_cache_file_is_valid_json(self, tmp_cache_dir: str) -> None:
        cache = TourCache(cache_dir=tmp_cache_dir, ttl_days=7)
        cache.set("json-test", {"numbers": [1, 2, 3]})
        filepath = os.path.join(tmp_cache_dir, "json-test.json")
        with open(filepath, "r") as f:
            parsed = json.load(f)
        assert parsed["data"]["numbers"] == [1, 2, 3]
        assert "_meta" in parsed
        assert "cached_at" in parsed["_meta"]
        assert "expires_at" in parsed["_meta"]

    def test_make_key(self, tmp_cache_dir: str) -> None:
        cache = TourCache(cache_dir=tmp_cache_dir, ttl_days=7)
        key = cache.make_key("12", 1, date="20260711")
        assert "cat-12" in key
        assert "area-1" in key
        assert "date-20260711" in key
