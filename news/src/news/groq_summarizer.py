"""Groq-powered news summarizer — uses the Groq SDK.

Same interface as gemini_summarizer, zen_summarizer:
    summarize_region()
    summarize_all()
    emoji_for()

Environment variable: GROQ_API_KEY
"""

import json
import logging
import os

from groq import Groq

from . import common
from .models import Article

logger = logging.getLogger(__name__)

_CACHE_FILE = os.path.join(common._CACHE_DIR, "summaries.json")


def summarize_region(
    region_key: str,
    region_name: str,
    articles: list[Article],
    model: str = "llama-3.3-70b-versatile",
    max_articles: int = 30,
) -> dict:
    top = common.proportional_select(articles, max_articles)
    if not top:
        return {
            "region": region_key,
            "region_name": region_name,
            "articles": [],
            "error": None,
        }

    ckey = common.cache_key(region_key, top, model)
    cache = common.load_cache(_CACHE_FILE)
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
    user_msg = common.user_prompt(region_name, top)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": common.get_system_prompt()},
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
    data = common.parse_json_response(content)
    if data is None:
        return {
            "region": region_key,
            "region_name": region_name,
            "articles": [],
            "error": "Failed to parse model response as JSON",
        }

    articles_out = data.get("articles", [])
    common.recover_urls(articles_out, top)

    result = {
        "region": region_key,
        "region_name": region_name,
        "articles": articles_out,
        "error": None,
    }

    result = common.post_process_results(result, top, region_key)

    cache[ckey] = result
    common.save_cache(_CACHE_FILE, cache)
    return result


def summarize_all(
    articles_by_region: dict[str, list[Article]],
    region_names: dict[str, str] | None = None,
    model: str = "llama-3.3-70b-versatile",
    max_articles: int = 10,
) -> list[dict]:
    names = region_names or {}
    return common.run_parallel(
        articles_by_region,
        names,
        summarize_region,
        model=model,
        max_articles=max_articles,
    )


def emoji_for(region_key: str) -> str:
    return common.emoji_for(region_key)
