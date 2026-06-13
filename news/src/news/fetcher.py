import logging
from datetime import datetime, timezone

import feedparser
import yaml

from .models import Article, FeedConfig, RegionConfig

logger = logging.getLogger(__name__)


def _load_config(config_path: str) -> dict[str, RegionConfig]:
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    regions: dict[str, RegionConfig] = {}
    for key, val in raw.get("regions", {}).items():
        feeds = [FeedConfig(**fc) for fc in val.get("feeds", [])]
        regions[key] = RegionConfig(name=val["name"], feeds=feeds)
    return regions


def _parse_date(entry) -> str:
    """Extract a publish date string from a feed entry."""
    for attr in ("published_parsed", "updated_parsed"):
        tup = getattr(entry, attr, None)
        if tup:
            try:
                dt = datetime(*tup[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    return ""


def _extract_url(entry) -> str:
    """Extract the best possible article URL from a feed entry.

    Priority: links[].href (alternate/html) > id/guid > link fallback.
    """
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


def _fetch_feed(feed_cfg: FeedConfig) -> list[Article]:
    """Fetch a single RSS feed, returning a list of Articles."""
    parsed = feedparser.parse(feed_cfg.url)
    articles: list[Article] = []
    for entry in parsed.entries:
        title = getattr(entry, "title", "") or ""
        url = _extract_url(entry)
        description = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        published = _parse_date(entry)
        articles.append(
            Article(
                title=title,
                url=url,
                description=description,
                source_name=feed_cfg.source,
                published=published,
                region="",  # filled by caller
            )
        )
    return articles


def fetch_all_articles(config_path: str = "config.yaml") -> dict[str, list[Article]]:
    """Fetch articles from all regions/feeds defined in config.

    Returns {region_key: [Article, ...]} where each region's articles
    are sorted newest-first and deduplicated by URL within the region.
    """
    regions = _load_config(config_path)
    result: dict[str, list[Article]] = {}

    for key, reg in regions.items():
        seen: set[str] = set()
        region_articles: list[Article] = []

        for feed_cfg in reg.feeds:
            try:
                articles = _fetch_feed(feed_cfg)
            except Exception as exc:
                logger.warning("Feed failed [%s] %s: %s", feed_cfg.source, feed_cfg.url, exc)
                continue

            for art in articles:
                if art.url in seen:
                    continue
                seen.add(art.url)
                art.region = key
                region_articles.append(art)

        # Keep articles in per-feed RSS order (feeds list important stories first).
        result[key] = region_articles

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    articles_by_region = fetch_all_articles()
    for region, arts in articles_by_region.items():
        print(f"{region}: {len(arts)} articles")
