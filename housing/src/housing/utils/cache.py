"""파일 기반 캐시.

API 응답을 JSON 파일로 캐싱하여 중복 호출을 방지합니다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FileCache:
    """JSON 파일 기반 캐시.

    Args:
        cache_dir: 캐시 디렉토리 경로 (기본: .cache)
        ttl_hours: 캐시 유효 시간 (시간 단위, 기본: 6)
    """

    def __init__(self, cache_dir: str = ".cache", ttl_hours: int = 6):
        self._cache_dir = Path(cache_dir)
        self._ttl_seconds = ttl_hours * 3600
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(self, url: str, params: Optional[dict[str, Any]] = None) -> str:
        """URL + 파라미터로 캐시 키(파일명)를 생성합니다."""
        raw = url
        if params:
            # API 키는 키 생성에서 제외 (캐시 재사용성)
            clean_params = {k: v for k, v in params.items() if k != "serviceKey"}
            raw += json.dumps(clean_params, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    def get(self, url: str, params: Optional[dict[str, Any]] = None) -> Optional[Any]:
        """캐시에서 데이터를 조회합니다.

        Returns:
            캐시 데이터 (유효기간 내) 또는 None
        """
        key = self._make_key(url, params)
        path = self._cache_path(key)

        if not path.exists():
            return None

        # 유효기간 확인
        mtime = path.stat().st_mtime
        if time.time() - mtime > self._ttl_seconds:
            logger.debug("Cache expired: %s", key)
            path.unlink(missing_ok=True)
            return None

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            logger.debug("Cache hit: %s", key)
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Cache read error: %s - %s", key, e)
            path.unlink(missing_ok=True)
            return None

    def set(
        self, url: str, data: Any,
        params: Optional[dict[str, Any]] = None,
    ) -> None:
        """데이터를 캐시에 저장합니다."""
        key = self._make_key(url, params)
        path = self._cache_path(key)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("Cache saved: %s (%d bytes)", key, path.stat().st_size)
        except OSError as e:
            logger.warning("Cache write error: %s - %s", key, e)

    def clear(self) -> None:
        """모든 캐시 파일을 삭제합니다."""
        count = 0
        for f in self._cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        logger.info("Cache cleared: %d files removed", count)

    def clear_old(self, ttl_hours: Optional[int] = None) -> int:
        """유효기간이 지난 캐시만 삭제합니다.

        Returns:
            삭제된 파일 수
        """
        ttl = (ttl_hours or 6) * 3600
        now = time.time()
        count = 0
        for f in self._cache_dir.glob("*.json"):
            if now - f.stat().st_mtime > ttl:
                f.unlink()
                count += 1
        if count:
            logger.info("Cleared %d expired cache files", count)
        return count

    def get_path(self) -> str:
        return str(self._cache_dir)


class NullCache:
    """캐시를 사용하지 않는 더미 구현 (테스트용)."""

    def get(self, url: str, params: Optional[dict[str, Any]] = None) -> Optional[Any]:
        return None

    def set(self, url: str, data: Any, params: Optional[dict[str, Any]] = None) -> None:
        pass

    def clear(self) -> None:
        pass

    def clear_old(self, ttl_hours: Optional[int] = None) -> int:
        return 0

    def get_path(self) -> str:
        return "/dev/null"
