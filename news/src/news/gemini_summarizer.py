"""Gemini-powered news summarizer — drop-in alternative to groq_summarizer.py.

Same interface: summarize_region(), summarize_all(), emoji_for().
Uses google-genai SDK (gemini-2.5-flash-lite) with JSON structured output.

Environment variable: GEMINI_API_KEY (or GOOGLE_API_KEY as fallback).
"""

import json
import logging
import os
import time

from google import genai

from . import common
from .models import Article

logger = logging.getLogger(__name__)

_CACHE_FILE = os.path.join(common._CACHE_DIR, "summaries_gemini.json")


def summarize_region(
    region_key: str,
    region_name: str,
    articles: list[Article],
    model: str = "gemini-2.5-flash-lite",
    max_articles: int = 30,
) -> dict:
    """Summarize articles for one region using Gemini."""
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

    user_msg = common.user_prompt(region_name, top)

    last_err = None
    data = None
    for attempt in range(1, 4):
        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_msg,
                config={
                    "system_instruction": common.get_system_prompt(),
                    "response_mime_type": "application/json",
                    "temperature": 0.3,
                    "max_output_tokens": 8192,
                },
            )
        except Exception as exc:
            last_err = str(exc)
            if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
                wait = attempt * 15
                logger.warning(
                    "Gemini rate limited on %s (attempt %d/3), waiting %ds",
                    region_key, attempt, wait
                )
                time.sleep(wait)
            else:
                logger.error("Gemini API call failed for %s: %s", region_key, exc)
                return {
                    "region": region_key,
                    "region_name": region_name,
                    "articles": [],
                    "error": last_err,
                }
            continue

        content = response.text or "{}"
        data = common.parse_json_response(content)
        if data is None:
            last_err = "Failed to parse Gemini response as JSON"
            logger.warning("%s on %s (attempt %d/3)", last_err, region_key, attempt)
            if attempt < 3:
                time.sleep(attempt * 5)
            continue

        if not data.get("articles"):
            last_err = "Model returned empty articles list"
            logger.warning("%s for %s (attempt %d/3)", last_err, region_key, attempt)
            if attempt < 3:
                time.sleep(attempt * 5)
            continue

        break  # success
    else:
        return {
            "region": region_key,
            "region_name": region_name,
            "articles": [],
            "error": last_err,
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

    common.cache_put(_CACHE_FILE, ckey, result)
    return result


def summarize_all(
    articles_by_region: dict[str, list[Article]],
    region_names: dict[str, str] | None = None,
    model: str = "gemini-2.5-flash-lite",
    max_articles: int = 10,
) -> list[dict]:
    """Summarize articles for all regions using Gemini (parallel)."""
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
