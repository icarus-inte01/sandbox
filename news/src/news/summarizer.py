import hashlib
import html
import json
import logging
import os
import re
import time

from groq import Groq

from .models import Article

logger = logging.getLogger(__name__)

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", ".cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "summaries.json")

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
{"articles": [{"index": N, "title": "...", "url": "...", "one_liner": "...", "significance": "..."}]}
"index" is the article number [N] from the provided list (1-based). Every field must be non-empty. The title must be translated to Korean."""


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
    model: str = "llama-3.3-70b-versatile",
    max_articles: int = 30,
) -> dict:
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
        logger.info("Cache hit for %s", region_key)
        return cached

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {
            "region": region_key,
            "region_name": region_name,
            "articles": [],
            "error": "GROQ_API_KEY environment variable not set",
        }

    client = Groq(api_key=api_key)
    user_msg = _user_prompt(region_name, top)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=8192,
        )
    except Exception as exc:
        err_str = str(exc)
        if "rate_limit" in err_str.lower() or "429" in err_str:
            logger.warning("Rate limited on %s — cached results will be used next time", region_key)
        else:
            logger.error("Groq API call failed for %s: %s", region_key, exc)
        return {
            "region": region_key,
            "region_name": region_name,
            "articles": [],
            "error": err_str,
        }

    content = resp.choices[0].message.content or "{}"

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("JSON parse failed for %s, trying regex fallback", region_key)
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
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
    model: str = "llama-3.3-70b-versatile",
    max_articles: int = 10,
) -> list[dict]:
    results: list[dict] = []
    for key, articles in articles_by_region.items():
        name = (region_names or {}).get(key, key)
        result = summarize_region(key, name, articles, model=model, max_articles=max_articles)
        results.append(result)
    return results


def emoji_for(region_key: str) -> str:
    return _REGION_EMOJI.get(region_key, "🌐")
