"""뉴스 기사 데이터 모델."""

from dataclasses import dataclass


@dataclass
class Article:
    """수집된 뉴스 기사 하나."""
    title: str
    url: str
    snippet: str
    published_date: str = ""
    source: str = ""

    @property
    def domain(self) -> str:
        """URL에서 도메인 추출."""
        try:
            from urllib.parse import urlparse
            return urlparse(self.url).netloc
        except Exception:
            return ""

    def __str__(self) -> str:
        return f"{self.title} ({self.source or self.domain})"
