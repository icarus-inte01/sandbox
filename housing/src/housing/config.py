"""설정 로더.

config.yaml 파일에서 설정을 로드하고 환경변수로 치환합니다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

# 프로젝트 루트 (이 파일 기준 src/housing/config.py → 3단계 위)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _substitute_env(value: Any) -> Any:
    """문자열 내 ${ENV_VAR} 패턴을 환경변수로 치환."""
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return re.sub(r"\$\{(\w+)\}", _replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(item) for item in value]
    return value


def load_config(path: str | None = None) -> dict[str, Any]:
    """설정 파일을 로드하고 환경변수를 치환하여 반환합니다.

    Args:
        path: 설정 파일 경로 (None이면 기본 경로 사용)

    Returns:
        설정 딕셔너리
    """
    if path is None:
        path = str(PROJECT_ROOT / "config.yaml")

    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return _substitute_env(config)


class Config:
    """타입 세이프 설정 접근자."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or load_config()

    @classmethod
    def from_file(cls, path: str) -> "Config":
        return cls(load_config(path))

    @property
    def api_keys(self) -> dict[str, str]:
        return self._config.get("api_keys", {})

    @property
    def data_go_kr_key(self) -> str:
        return self.api_keys.get("data_go_kr", "")

    @property
    def vworld_api_key(self) -> str:
        return self.api_keys.get("vworld", "")

    @property
    def weights(self) -> dict[str, float]:
        return self._config.get("weights", {})

    @property
    def request_delay(self) -> float:
        return self._config.get("api", {}).get("request_delay", 0.5)

    @property
    def max_retries(self) -> int:
        return self._config.get("api", {}).get("max_retries", 3)

    @property
    def timeout(self) -> int:
        return self._config.get("api", {}).get("timeout", 30)

    @property
    def per_page(self) -> int:
        return self._config.get("api", {}).get("per_page", 100)

    @property
    def cache_enabled(self) -> bool:
        return self._config.get("cache", {}).get("enabled", True)

    @property
    def cache_ttl_hours(self) -> int:
        return self._config.get("cache", {}).get("ttl_hours", 6)

    @property
    def cache_dir(self) -> str:
        return self._config.get("cache", {}).get("dir", ".cache")

    @property
    def brand_score_overrides(self) -> dict[str, float]:
        return self._config.get("brand_score_overrides", {})

    @property
    def region_score_overrides(self) -> dict[str, float]:
        return self._config.get("region_score_overrides", {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)
