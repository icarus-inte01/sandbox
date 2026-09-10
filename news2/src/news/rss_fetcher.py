"""국내 언론사 국제부 RSS 수집 모듈."""

import logging
import re
import urllib.request
from datetime import datetime, timezone

import feedparser

from .models import Article

logger = logging.getLogger(__name__)

_BAD_ENTITY_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);)")
_USER_AGENT = "Mozilla/5.0 (compatible; news2-digest/1.0)"


def _fetch_raw(url: str) -> str:
    """피드 원문을 가져오고, 잘못된(&amp;로 이스케이프되지 않은) & 문자를 보정한다.

    일부 언론사 피드(예: 한국경제)가 본문에 "R&D"처럼 이스케이프되지 않은
    &를 그대로 내보내는 경우가 있는데, 이러면 feedparser가 entries를 아예
    0건으로 반환해버린다.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return _BAD_ENTITY_RE.sub("&amp;", raw)


def _parse_date(entry) -> str:
    """피드 항목에서 발행일을 ISO 문자열로 추출."""
    for attr in ("published_parsed", "updated_parsed"):
        tup = getattr(entry, attr, None)
        if tup:
            try:
                return datetime(*tup[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return ""


def _extract_url(entry) -> str:
    """피드 항목에서 기사 URL을 추출."""
    for lnk in getattr(entry, "links", []):
        if lnk.get("rel") == "alternate" and lnk.get("type") == "text/html":
            href = lnk.get("href", "")
            if href:
                return href
    for field in ("id", "guid"):
        val = getattr(entry, field, None)
        if val and isinstance(val, str) and val.startswith("http"):
            return val
    return getattr(entry, "link", "") or ""


def fetch_feed(url: str, source: str) -> list[Article]:
    """단일 RSS 피드를 가져와 Article 리스트로 변환."""
    parsed = feedparser.parse(_fetch_raw(url))
    articles = []
    for entry in parsed.entries:
        title = getattr(entry, "title", "") or ""
        article_url = _extract_url(entry)
        snippet = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        articles.append(Article(
            title=title,
            url=article_url,
            snippet=snippet,
            published_date=_parse_date(entry),
            source=source,
        ))
    return articles


def fetch_all(feeds: list[dict]) -> list[Article]:
    """설정된 모든 피드를 가져와 URL 기준으로 중복 제거된 단일 리스트로 반환."""
    seen: set[str] = set()
    articles: list[Article] = []
    for feed_cfg in feeds:
        url = feed_cfg["url"]
        source = feed_cfg.get("source", url)
        try:
            fetched = fetch_feed(url, source)
        except Exception as exc:
            logger.warning("Feed failed [%s] %s: %s", source, url, exc)
            continue

        count = 0
        for art in fetched:
            if not art.url or art.url in seen:
                continue
            seen.add(art.url)
            articles.append(art)
            count += 1
        print(f"  [{source}] {count}건 수집")

    return articles
