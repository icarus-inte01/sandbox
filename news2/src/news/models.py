"""뉴스 기사 데이터 모델."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class Article:
    """수집된 뉴스 기사 하나."""
    title: str
    url: str
    snippet: str
    published_date: str = ""
    region: str = ""
    source: str = ""
    score: float = 0.0

    @property
    def domain(self) -> str:
        """URL에서 도메인 추출."""
        try:
            from urllib.parse import urlparse
            return urlparse(self.url).netloc
        except Exception:
            return ""

    def __str__(self) -> str:
        return f"[{self.region}] {self.title} ({self.source or self.domain})"


@dataclass
class ResearchReport:
    """Research 모드 결과 보고서."""
    query: str
    answer: str
    sources: List[str] = field(default_factory=list)
    raw_content: str = ""
    fetch_time: float = 0.0
    region: str = ""

    @property
    def source_count(self) -> int:
        return len(self.sources)
