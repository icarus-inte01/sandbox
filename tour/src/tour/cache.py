"""파일 기반 캐시 — 1주일 TTL로 TourAPI 응답을 로컬에 저장."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any


class TourCache:
    """파일 기반 캐시.

    Attributes:
        cache_dir: 캐시 파일을 저장할 디렉토리
        ttl_days: 캐시 유효기간 (일)
    """

    def __init__(self, cache_dir: str = ".cache", ttl_days: int = 7) -> None:
        self.cache_dir = cache_dir
        self.ttl_days = ttl_days
        os.makedirs(self.cache_dir, exist_ok=True)

    def _make_key(self, category: str, area_code: int, **extra: str) -> str:
        """캐시 키 생성.

        Args:
            category: 카테고리 식별자 (예: "12", "festival")
            area_code: 지역 코드
            **extra: 추가 식별자 (예: date=20260711)

        Returns:
            캐시 키 문자열
        """
        parts = [f"cat-{category}", f"area-{area_code}"]
        for k, v in sorted(extra.items()):
            parts.append(f"{k}-{v}")
        return "-".join(parts)

    def _file_path(self, key: str) -> str:
        """캐시 키에 해당하는 파일 경로."""
        # 파일명에 사용할 수 없는 문자 치환
        safe_key = key.replace("/", "_").replace("\\", "_")
        return os.path.join(self.cache_dir, f"{safe_key}.json")

    def get(self, key: str) -> dict[str, Any] | None:
        """캐시에서 데이터 조회.

        Args:
            key: 캐시 키

        Returns:
            캐시된 데이터 (dict) 또는 None (미스/만료)
        """
        filepath = self._file_path(key)
        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                entry = json.load(f)

            expires_at = entry.get("_meta", {}).get("expires_at", "")
            if expires_at and time.time() >= expires_at:
                # 만료됨 → 삭제
                os.remove(filepath)
                return None

            return entry.get("data")
        except (json.JSONDecodeError, OSError):
            # 손상된 캐시 파일 삭제
            try:
                os.remove(filepath)
            except OSError:
                pass
            return None

    def set(self, key: str, data: dict[str, Any]) -> None:
        """데이터를 캐시에 저장.

        Args:
            key: 캐시 키
            data: 저장할 데이터
        """
        now = time.time()
        expires_at = now + (self.ttl_days * 86400)  # 일 → 초
        entry = {
            "_meta": {
                "key": key,
                "cached_at": now,
                "expires_at": expires_at,
                "cached_at_iso": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
                "expires_at_iso": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
                "ttl_days": self.ttl_days,
            },
            "data": data,
        }
        filepath = self._file_path(key)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)

    def clear(self) -> None:
        """전체 캐시 삭제."""
        if not os.path.exists(self.cache_dir):
            return
        for filename in os.listdir(self.cache_dir):
            if filename.endswith(".json"):
                os.remove(os.path.join(self.cache_dir, filename))

    def clear_expired(self) -> int:
        """만료된 캐시만 삭제.

        Returns:
            삭제된 캐시 파일 개수
        """
        if not os.path.exists(self.cache_dir):
            return 0
        now = time.time()
        removed = 0
        for filename in os.listdir(self.cache_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(self.cache_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                expires_at = entry.get("_meta", {}).get("expires_at", 0)
                if now >= expires_at:
                    os.remove(filepath)
                    removed += 1
            except (json.JSONDecodeError, OSError):
                os.remove(filepath)
                removed += 1
        return removed

    def make_key(self, category: str, area_code: int, **extra: str) -> str:
        """공개 캐시 키 생성 메서드."""
        return self._make_key(category, area_code, **extra)
