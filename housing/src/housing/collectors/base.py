"""수집기 기본 클래스."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.housing.config import Config
from src.housing.models import SaleListing
from src.housing.utils.api_client import OdcloudClient
from src.housing.utils.cache import FileCache, NullCache

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """모든 데이터 수집기의 기본 클래스.

    공통 기능:
    - Config 접근
    - API 클라이언트 (OdcloudClient)
    - 파일 캐시
    - 소스명 관리
    """

    def __init__(self, config: Optional[Any] = None):
        self.config = config if config is not None else Config()
        self.client = OdcloudClient(self.config)
        if self.config.cache_enabled:
            self.cache = FileCache(
                cache_dir=self.config.cache_dir,
                ttl_hours=self.config.cache_ttl_hours,
            )
        else:
            self.cache = NullCache()
        self.source_name: str = "base"

    @abstractmethod
    def collect(self, **kwargs) -> list[SaleListing]:
        """데이터를 수집하여 SaleListing 리스트로 반환합니다."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(source={self.source_name})"
