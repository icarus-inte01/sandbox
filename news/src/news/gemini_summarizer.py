"""Gemini-powered news summarizer — drop-in alternative to summarizer.py.

Same interface: summarize_region(), summarize_all(), emoji_for().
Uses google-genai SDK (gemini-2.5-flash-lite) with JSON structured output.

Environment variable: GEMINI_API_KEY (or GOOGLE_API_KEY as fallback).
"""

import hashlib
import html
import json
import logging
import os
import re
import time

from google import genai
from google.genai import errors as gemini_errors

from .models import Article

logger = logging.getLogger(__name__)

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", ".cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "summaries_gemini.json")

_REGION_EMOJI = {
    "north_america": "🌎",
    "europe": "🌍",
    "asia": "🌏",
    "middle_east": "🌍",
    "latin_america": "🌎",
    "africa": "🌍",
    "oceania": "🌏",
}

SYSTEM_PROMPT = (
    "You are a Korean news summarization assistant. Given a list of recent news "
    "articles from a specific region, select 5 important stories. For each, provide:\n"
    "1. A detailed Korean summary (4-5 sentences). Cover who, what, when, where, why, "
    "and the key context or implications.\n"
    "2. The title translated into Korean (do NOT keep the original language title)\n"
    "3. The URL from the list\n"
    "4. A 2-3 sentence Korean explanation on why this matters and what impact it may have.\n\n"
    "LANGUAGE RULE: You MUST write everything in Korean. If the article text is in "
    "Japanese, Chinese, Portuguese, Spanish, Arabic, or any other language — ignore "
    "the article language and write your output in Korean. ALL three fields — title, "
    "one_liner, and significance — must ALWAYS be in Korean. Writing any field in "
    "Japanese, Chinese, Portuguese, Spanish, or any language other than Korean is "
    "strictly forbidden.\n\n"
    'Respond in valid JSON:\n'
    '{"articles": [{"index": N, "title": "...", "url": "...", "one_liner": "...", "significance": "..."}]}\n'
    '"index" is the article number [N] from the provided list (1-based). Every field must be non-empty. The title must be translated to Korean.'
)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


def _cache_key(region_key: str, articles: list[Article], model: str) -> str:
    raw = region_key + model + "".join(a.title + a.url for a in articles)
    return hashlib.sha256(raw.encode()).hexdigest()


def _load_cache() -> dict:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict):
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except OSError as exc:
        logger.warning("Gemini cache write failed: %s", exc)


def _user_prompt(region_name: str, articles: list[Article]) -> str:
    lines = [f"Region: {region_name}", f"Total articles available: {len(articles)}", ""]
    for i, art in enumerate(articles, 1):
        desc = _strip_html(art.description)
        if len(desc) > 500:
            desc = desc[:500] + "…"
        lines.append(f"[{i}] Title: {art.title}")
        lines.append(f"    Source: {art.source_name}")
        lines.append(f"    Description: {desc}")
        lines.append("")
    return "\n".join(lines)


def _word_jaccard(a: str, b: str) -> float:
    """Jaccard similarity of word sets between two strings (0.0–1.0)."""
    wa = set(re.sub(r"[^\w]", " ", a.lower()).split())
    wb = set(re.sub(r"[^\w]", " ", b.lower()).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _cross_feed_score(art: Article, groups: dict[str, list[Article]]) -> int:
    """How many *other* feeds carry a story with a similar title."""
    nkey = _norm_title(art.title)
    score = 0
    for src, arts in groups.items():
        if src == art.source_name:
            continue
        for other in arts:
            if _word_jaccard(nkey, _norm_title(other.title)) > 0.35:
                score += 1
                break
    return score


def _proportional_select(articles: list[Article], n: int) -> list[Article]:
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
        arts.sort(key=lambda a: _cross_feed_score(a, groups), reverse=True)

    per_feed = n // len(group_names)
    remainder = n % len(group_names)
    selected: list[Article] = []
    for i, name in enumerate(group_names):
        take = per_feed + (1 if i < remainder else 0)
        selected.extend(groups[name][:take])
    return selected


def summarize_region(
    region_key: str,
    region_name: str,
    articles: list[Article],
    model: str = "gemini-2.5-flash-lite",
    max_articles: int = 30,
) -> dict:
    """Summarize articles for one region using Gemini.

    Returns the same dict shape as summarizer.summarize_region():
        {"region": ..., "region_name": ..., "articles": [...], "error": None|str}
    """
    top = _proportional_select(articles, max_articles)
    if not top:
        return {
            "region": region_key,
            "region_name": region_name,
            "articles": [],
            "error": None,
        }

    ckey = _cache_key(region_key, top, model)
    cache = _load_cache()
    cached = cache.get(ckey)
    if cached is not None:
        logger.info("Gemini cache hit for %s", region_key)
        return cached

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {
            "region": region_key,
            "region_name": region_name,
            "articles": [],
            "error": "GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set",
        }

    user_msg = _user_prompt(region_name, top)

    last_err = None
    for attempt in range(1, 4):
        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_msg,
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "temperature": 0.3,
                    "max_output_tokens": 8192,
                },
            )
            break
        except Exception as exc:
            last_err = str(exc)
            if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
                wait = attempt * 15
                logger.warning("Gemini rate limited on %s (attempt %d/3), waiting %ds", region_key, attempt, wait)
                time.sleep(wait)
            else:
                logger.error("Gemini API call failed for %s: %s", region_key, exc)
                return {
                    "region": region_key,
                    "region_name": region_name,
                    "articles": [],
                    "error": last_err,
                }
    else:
        return {
            "region": region_key,
            "region_name": region_name,
            "articles": [],
            "error": last_err,
        }

    content = response.text or "{}"

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Gemini JSON parse failed for %s, trying regex fallback", region_key)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return {
                    "region": region_key,
                    "region_name": region_name,
                    "articles": [],
                    "error": "Failed to parse Gemini response as JSON",
                }
        else:
            return {
                "region": region_key,
                "region_name": region_name,
                "articles": [],
                "error": "No JSON found in Gemini response",
            }

    articles_out = data.get("articles", [])
    for art in articles_out:
        idx = art.get("index")
        if idx is not None and 1 <= idx <= len(top):
            art["url"] = top[idx - 1].url

    result = {
        "region": region_key,
        "region_name": region_name,
        "articles": articles_out,
        "error": None,
    }

    cache[ckey] = result
    _save_cache(cache)
    return result


def summarize_all(
    articles_by_region: dict[str, list[Article]],
    region_names: dict[str, str] | None = None,
    model: str = "gemini-2.5-flash-lite",
    max_articles: int = 10,
) -> list[dict]:
    """Summarize articles for all regions using Gemini.

    Returns list of dicts with the same shape as summarizer.summarize_all().
    """
    results: list[dict] = []
    for idx, (key, articles) in enumerate(articles_by_region.items()):
        name = (region_names or {}).get(key, key)
        result = summarize_region(key, name, articles, model=model, max_articles=max_articles)
        results.append(result)
        if idx < len(articles_by_region) - 1:
            time.sleep(3)  # brief cooldown between regions
    return results


def emoji_for(region_key: str) -> str:
    return _REGION_EMOJI.get(region_key, "🌐")
