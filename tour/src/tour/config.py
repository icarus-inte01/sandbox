"""설정 로더 — YAML 설정 파일을 로드하고 환경변수를 치환."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class Config:
    """전역 설정."""
    api_keys: dict[str, str] = field(default_factory=dict)
    api: dict[str, Any] = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)
    sort: dict[str, str] = field(default_factory=dict)
    categories: list[dict[str, Any]] = field(default_factory=list)

    def get_categories(self) -> list[dict[str, Any]]:
        """설정된 카테고리 목록 반환."""
        return self.categories

    def get_sort_order(self) -> str:
        """정렬 방식 반환 (기본 'O')."""
        return self.sort.get("arrange", "O")

    def get_cache_ttl_days(self) -> int:
        """캐시 TTL(일) 반환 (기본 7)."""
        return int(self.cache.get("ttl_days", 7))

    def get_cache_dir(self) -> str:
        """캐시 디렉토리 반환 (기본 '.cache')."""
        return self.cache.get("dir", ".cache")

    def get_base_url(self) -> str:
        """TourAPI 기본 URL 반환."""
        return self.api.get("base_url", "http://apis.data.go.kr/B551011/KorService1")

    def get_api_setting(self, key: str, default: Any = None) -> Any:
        """API 설정값 반환."""
        return self.api.get(key, default)


def _resolve_env_vars(value: Any) -> Any:
    """문자열 내 ${ENV_VAR} 패턴을 환경변수로 치환."""
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, "")
        return re.sub(r"\$\{(\w+)\}", _replace, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


def load_config(path: str = "config.yaml") -> Config:
    """YAML 설정 파일을 로드하고 Config 객체 반환."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    resolved = _resolve_env_vars(raw)
    return Config(**resolved)
