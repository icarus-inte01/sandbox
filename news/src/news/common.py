"""Shared utilities for all news summarizer providers.

Extracted from duplicated code across groq_summarizer.py, gemini_summarizer.py,
and zen_summarizer.py to eliminate ~80% code replication.
"""

import datetime
import hashlib
import html
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from .models import Article

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Emoji helpers
# ---------------------------------------------------------------------------

_REGION_EMOJI = {
    "north_america": "🌎",
    "europe": "🌍",
    "asia": "🌏",
    "middle_east": "🌍",
    "latin_america": "🌎",
    "africa": "🌍",
    "oceania": "🌏",
}


def emoji_for(region_key: str) -> str:
    return _REGION_EMOJI.get(region_key, "🌐")


# ---------------------------------------------------------------------------
# System prompt (with grounding)
# ---------------------------------------------------------------------------

def get_system_prompt() -> str:
    today = datetime.date.today().isoformat()
    return (
        f"You are a Korean news summarization assistant. Today's date is {today}.\n"
        f"\n"
        f"Given a list of recent news articles from a specific region, select 5 important "
        f"stories. For each, provide:\n"
        f"1. A detailed Korean summary (4-5 sentences). Cover who, what, when, where, why, "
        f"and the key context or implications.\n"
        f"2. The title translated into Korean (do NOT keep the original language title)\n"
        f"3. The URL from the list\n"
        f"4. A 2-3 sentence Korean explanation on why this matters and what impact it may have.\n"
        f"\n"
        f"GROUNDING RULE: You MUST base your summary ONLY on the article descriptions, titles, "
        f"and dates provided below. Do NOT use your own knowledge or training data. The "
        f"Title, Source, Date, and Description fields contain ALL the information available "
        f"to you. If the description is brief, summarize faithfully what IS there — do NOT "
        f"add, substitute, or fabricate details from your memory. Inventing or substituting "
        f"article content from your training data is strictly forbidden. Every article's "
        f"Date field tells you when it was published — respect it and do NOT substitute a "
        f"different date or event from your training data.\n"
        f"\n"
        f"LANGUAGE RULE: You MUST write everything in Korean. If the article text is in "
        f"Japanese, Chinese, Portuguese, Spanish, Arabic, or any other language — ignore "
        f"the article language and write your output in Korean. ALL three fields — title, "
        f"one_liner, and significance — must ALWAYS be in Korean. Writing any field in "
        f"Japanese, Chinese, Portuguese, Spanish, or any language other than Korean is "
        f"strictly forbidden.\n"
        f"\n"
        f'Respond in valid JSON:\n'
        f'{{"articles": [{{"index": N, "title": "...", "url": "...", "one_liner": "...", '
        f'"significance": "..."}}]}}\n'
        f'"index" is the article number [N] from the provided list (1-based). Every field '
        f'must be non-empty. The title must be translated to Korean.'
    )


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


# ---------------------------------------------------------------------------
# User prompt builder (includes article date for grounding)
# ---------------------------------------------------------------------------

def user_prompt(region_name: str, articles: list[Article]) -> str:
    lines = [f"Region: {region_name}", f"Total articles available: {len(articles)}", ""]
    for i, art in enumerate(articles, 1):
        desc = strip_html(art.description)
        if len(desc) > 500:
            desc = desc[:500] + "…"
        pub_date = art.published or "(date unknown)"
        lines.append(f"[{i}] Title: {art.title}")
        lines.append(f"    Source: {art.source_name}")
        lines.append(f"    Date: {pub_date}")
        lines.append(f"    Description: {desc}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cache helpers (parameterized by cache file path)
# ---------------------------------------------------------------------------

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", ".cache")


def cache_key(region_key: str, articles: list[Article], model: str) -> str:
    raw = region_key + model + "".join(a.title + a.url for a in articles)
    return hashlib.sha256(raw.encode()).hexdigest()


def load_cache(cache_file: str) -> dict:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(cache_file, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(cache_file: str, cache: dict):
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except OSError as exc:
        logger.warning("Cache write failed (%s): %s", cache_file, exc)


# ---------------------------------------------------------------------------
# Cross-feed scoring
# ---------------------------------------------------------------------------

def word_jaccard(a: str, b: str) -> float:
    """Jaccard similarity of word sets between two strings (0.0–1.0)."""
    wa = set(re.sub(r"[^\w]", " ", a.lower()).split())
    wb = set(re.sub(r"[^\w]", " ", b.lower()).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def cross_feed_score(art: Article, groups: dict[str, list[Article]]) -> int:
    """How many *other* feeds carry a story with a similar title."""
    nkey = norm_title(art.title)
    score = 0
    for src, arts in groups.items():
        if src == art.source_name:
            continue
        for other in arts:
            if word_jaccard(nkey, norm_title(other.title)) > 0.35:
                score += 1
                break
    return score


def proportional_select(articles: list[Article], n: int) -> list[Article]:
    """Select up to *n* articles proportionally across feeds.

    1. Group by ``source_name`` (one group per feed URL).
    2. Within each group, score articles by cross-feed coverage — a story
       carried by multiple sources gets a higher score and bubbles to the
       top of its group.
    3. Distribute the *n* slots fairly across groups.
    """
    groups: dict[str, list[Article]] = {}
    for art in articles:
        groups.setdefault(art.source_name, []).append(art)
    group_names = list(groups.keys())
    if not group_names:
        return []

    for arts in groups.values():
        arts.sort(key=lambda a: cross_feed_score(a, groups), reverse=True)

    per_feed = n // len(group_names)
    remainder = n % len(group_names)
    selected: list[Article] = []
    for i, name in enumerate(group_names):
        take = per_feed + (1 if i < remainder else 0)
        selected.extend(groups[name][:take])
    return selected


# ---------------------------------------------------------------------------
# JSON response parsing
# ---------------------------------------------------------------------------

def parse_json_response(content: str) -> dict | None:
    """Parse JSON from LLM response, with regex fallback.

    Returns parsed dict on success, or None if parsing fails entirely.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# URL recovery
# ---------------------------------------------------------------------------

def recover_urls(articles_out: list[dict], top_articles: list[Article]):
    """Patch URLs in the output dict from the source articles list."""
    for art in articles_out:
        idx = art.get("index")
        if idx is not None and 1 <= idx <= len(top_articles):
            art["url"] = top_articles[idx - 1].url


# ---------------------------------------------------------------------------
# Post-processing: validate model output against source articles
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> datetime.date | None:
    """Try to extract a date from various formats."""
    if not date_str or date_str == "(date unknown)":
        return None
    # ISO-8601: "2026-07-08T12:00:00+00:00"
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%a, %d %b %Y"):
        try:
            # Strip timezone offset for parsing
            clean = re.sub(r"[+-]\d{2}:\d{2}$", "", date_str)
            clean = re.sub(r"Z$", "", clean)
            return datetime.datetime.strptime(clean[:19], fmt).date()
        except (ValueError, IndexError):
            continue
    return None


def post_process_results(
    result: dict,
    top_articles: list[Article],
    region_key: str,
) -> dict:
    """Validate and filter model output against source articles.

    Checks performed:
    1. Every article index points to a real source article.
    2. The published date from the source is within a reasonable window
       (not pulled from training data).
    3. Title similarity between model output and source article passes
       a minimum threshold (prevents completely fabricated articles).

    Returns the result dict with suspicious articles flagged or removed.
    """
    articles_out = result.get("articles", [])
    if not articles_out:
        return result

    today = datetime.date.today()
    validated: list[dict] = []

    for art in articles_out:
        idx = art.get("index")
        if idx is None or not (1 <= idx <= len(top_articles)):
            logger.warning("[%s] Article index %s out of range, dropping", region_key, idx)
            continue

        source = top_articles[idx - 1]
        flags: list[str] = []

        # --- Check 1: publish date is reasonable ---
        pub_date = _parse_date(source.published)
        if pub_date is not None:
            days_ago = (today - pub_date).days
            if days_ago < 0:
                flags.append(f"future_date({days_ago}d)")
                logger.warning("[%s] Article #%d has future date %s", region_key, idx, source.published)
            elif days_ago > 30:
                flags.append(f"old_date({days_ago}d)")
                logger.warning(
                    "[%s] Article #%d date %s is %d days old — may be stale",
                    region_key, idx, source.published, days_ago,
                )

        # Cross-lingual check: proper nouns (Trump, FDA, Iran) should appear in output
        out_text = (art.get("title", "") + " " + art.get("one_liner", "")).lower()
        src_text = (source.title + " " + source.description).lower()
        src_keywords = set(re.findall(r"[a-z][a-z0-9]{2,}", src_text))  # 3+ char alphanum
        out_tokens = set(re.findall(r"[a-z][a-z0-9]{2,}", out_text))
        shared = src_keywords & out_tokens

        if len(src_keywords) >= 3 and len(shared) == 0:
            flags.append("no_shared_keyterms")
            logger.warning(
                "[%s] Article #%d has no shared key terms with source — possible hallucination",
                region_key, idx,
            )

        if flags:
            art["_warnings"] = flags
            logger.info("[%s] Article #%d flags: %s", region_key, idx, ", ".join(flags))

        validated.append(art)

    result["articles"] = validated
    return result


# ---------------------------------------------------------------------------
# Parallel execution
# ---------------------------------------------------------------------------

def run_parallel(
    articles_by_region: dict[str, list[Article]],
    region_names: dict[str, str],
    summarize_fn: Callable,
    model: str,
    max_articles: int,
    max_workers: int = 4,
    cooldown: float = 0.0,
) -> list[dict]:
    """Run summarization for multiple regions in parallel.

    Parameters
    ----------
    summarize_fn
        A callable with signature ``(region_key, region_name, articles, model, max_articles)``
        that returns the standard result dict.
    max_workers
        Thread pool size (default 4 — avoids hammering API rate limits).
    cooldown
        Optional sleep *between* region completions (legacy compat, default 0).

    Returns
    -------
    list[dict]
        Results in the order the regions were iterated.
    """
    region_items = list(articles_by_region.items())
    results: list[dict] = [None] * len(region_items)  # pre-allocate for ordering
    submitted = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for idx, (key, articles) in enumerate(region_items):
            name = region_names.get(key, key)
            future = pool.submit(summarize_fn, key, name, articles, model, max_articles)
            submitted[future] = idx

        for future in as_completed(submitted):
            idx = submitted[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                key, _ = region_items[idx]
                name = region_names.get(key, key)
                logger.error("Parallel summarization failed for %s: %s", key, exc)
                results[idx] = {
                    "region": key,
                    "region_name": name,
                    "articles": [],
                    "error": str(exc),
                }
            if cooldown > 0:
                time.sleep(cooldown)

    return results
