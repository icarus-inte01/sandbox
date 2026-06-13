"""Summarize news articles using the OpenCode Zen API (big-pickle / free models).

Same interface as ``summarizer`` and ``gemini_summarizer``:
    summarize_region()
    summarize_all()
    emoji_for()

Uses ``requests`` to call the OpenAI-compatible ``big-pickle`` endpoint.
"""

import hashlib
import html
import json
import logging
import os
import re
import time

import requests

from .models import Article

logger = logging.getLogger(__name__)

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", ".cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "summaries_zen.json")

_BASE_URL = "https://opencode.ai/zen/v1"

_REGION_EMOJI = {
    "north_america": "🌎",
    "europe": "🌍",
    "asia": "🌏",
    "middle_east": "🌍",
    "latin_america": "🌎",
    "africa": "🌍",
    "oceania": "🌏",
}

SYSTEM_PROMPT = """You are a Korean news summarization assistant. Given a list of recent news articles from a specific region, select 5 important stories. For each, provide:
1. A detailed Korean summary (4-5 sentences). Cover who, what, when, where, why, and the key context or implications.
2. The title translated into Korean (do NOT keep the original language title)
3. The URL from the list
4. A 2-3 sentence Korean explanation on why this matters and what impact it may have.

LANGUAGE RULE: You MUST write everything in Korean. If the article text is in Japanese, Chinese, Portuguese, Spanish, Arabic, or any other language — ignore the article language and write your output in Korean. ALL three fields — title, one_liner, and significance — must ALWAYS be in Korean. Writing any field in Japanese, Chinese, Portuguese, Spanish, or any language other than Korean is strictly forbidden.

Respond in valid JSON:
{"articles": [{"title": "...", "url": "...", "one_liner": "...", "significance": "..."}]}
Every field must be non-empty. The title must be translated to Korean."""


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
        logger.warning("Cache write failed: %s", exc)


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


# ---------------------------------------------------------------------------
# Cross-feed scoring (shared logic identical to summarizer / gemini_summarizer)
# ---------------------------------------------------------------------------

def _word_jaccard(a: str, b: str) -> float:
    wa = set(re.sub(r"[^\w]", " ", a.lower()).split())
    wb = set(re.sub(r"[^\w]", " ", b.lower()).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _cross_feed_score(art: Article, groups: dict[str, list[Article]]) -> int:
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


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def _zen_chat_completion(
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 8192,
) -> dict:
    """Call the OpenCode Zen chat completion endpoint.

    Returns the parsed JSON response object (the ``choices[0].message`` dict).
    """
    api_key = os.environ.get("OPENCODE_API_KEY")
    if not api_key:
        raise RuntimeError("OPENCODE_API_KEY environment variable not set")

    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(
        f"{_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def summarize_region(
    region_key: str,
    region_name: str,
    articles: list[Article],
    model: str = "big-pickle",
    max_articles: int = 30,
) -> dict:
    """Summarize articles for one region using OpenCode Zen.

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

    url_map: dict[str, str] = {}
    for art in top:
        key = _norm_title(art.title)
        if key not in url_map:
            url_map[key] = art.url

    ckey = _cache_key(region_key, top, model)
    cache = _load_cache()
    cached = cache.get(ckey)
    if cached is not None:
        logger.info("Zen cache hit for %s", region_key)
        return cached

    user_msg = _user_prompt(region_name, top)

    last_err = None
    for attempt in range(1, 4):
        try:
            data = _zen_chat_completion(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
            break
        except requests.HTTPError as exc:
            last_err = str(exc)
            status = exc.response.status_code if exc.response is not None else 0
            if status == 429 or status >= 500:
                wait = attempt * 10
                logger.warning("Zen API error %d on %s (attempt %d/3), waiting %ds", status, region_key, attempt, wait)
                time.sleep(wait)
            else:
                logger.error("Zen API call failed for %s: %s", region_key, exc)
                return {
                    "region": region_key,
                    "region_name": region_name,
                    "articles": [],
                    "error": last_err,
                }
        except Exception as exc:
            last_err = str(exc)
            logger.error("Zen API call failed for %s: %s", region_key, exc)
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

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {
            "region": region_key,
            "region_name": region_name,
            "articles": [],
            "error": "Empty response from Zen API",
        }

    if not content:
        content = "{}"

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("JSON parse failed for %s, trying regex fallback", region_key)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                return {
                    "region": region_key,
                    "region_name": region_name,
                    "articles": [],
                    "error": "Failed to parse model response as JSON",
                }
        else:
            return {
                "region": region_key,
                "region_name": region_name,
                "articles": [],
                "error": "No JSON found in model response",
            }

    articles_out = parsed.get("articles", [])
    for art in articles_out:
        t = art.get("title", "")
        original_url = url_map.get(_norm_title(t))
        if original_url:
            art["url"] = original_url

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
    model: str = "big-pickle",
    max_articles: int = 30,
) -> list[dict]:
    """Summarize articles for all regions using OpenCode Zen."""
    results: list[dict] = []
    for idx, (key, articles) in enumerate(articles_by_region.items()):
        name = (region_names or {}).get(key, key)
        result = summarize_region(key, name, articles, model=model, max_articles=max_articles)
        results.append(result)
        if idx < len(articles_by_region) - 1:
            time.sleep(1)  # brief cooldown
    return results


def emoji_for(region_key: str) -> str:
    return _REGION_EMOJI.get(region_key, "🌐")
