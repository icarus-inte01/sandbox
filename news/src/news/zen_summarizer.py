"""Summarize news articles using the OpenCode Zen API (big-pickle / free models).

Same interface as ``groq_summarizer`` and ``gemini_summarizer``:
    summarize_region()
    summarize_all()
    emoji_for()

Uses ``requests`` to call the OpenAI-compatible ``big-pickle`` endpoint.
"""

import json
import logging
import os
import time

import requests

from . import common
from .models import Article

logger = logging.getLogger(__name__)

_CACHE_FILE = os.path.join(common._CACHE_DIR, "summaries_zen.json")
_BASE_URL = "https://opencode.ai/zen/v1"


def _zen_chat_completion(
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 8192,
) -> dict:
    """Call the OpenCode Zen chat completion endpoint.

    Returns the parsed JSON response object (the full response dict).
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


def summarize_region(
    region_key: str,
    region_name: str,
    articles: list[Article],
    model: str = "big-pickle",
    max_articles: int = 30,
) -> dict:
    """Summarize articles for one region using OpenCode Zen."""
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
        logger.info("Zen cache hit for %s", region_key)
        return cached

    user_msg = common.user_prompt(region_name, top)

    last_err = None
    for attempt in range(1, 4):
        try:
            data = _zen_chat_completion(
                model=model,
                messages=[
                    {"role": "system", "content": common.get_system_prompt()},
                    {"role": "user", "content": user_msg},
                ],
            )
        except requests.HTTPError as exc:
            last_err = str(exc)
            status = exc.response.status_code if exc.response is not None else 0
            if status == 429 or status >= 500:
                wait = attempt * 10
                logger.warning(
                    "Zen API error %d on %s (attempt %d/3), waiting %ds",
                    status, region_key, attempt, wait
                )
                time.sleep(wait)
                continue
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
            # API call succeeded — parse the response
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                last_err = "Empty response from Zen API"
                logger.warning("%s (attempt %d/3)", last_err, attempt)
                if attempt < 3:
                    time.sleep(attempt * 5)
                continue

            if not content:
                content = "{}"

            parsed = common.parse_json_response(content)
            if parsed is not None:
                break
            else:
                last_err = "No JSON found in model response"
                logger.warning("%s for %s (attempt %d/3): %s", last_err, region_key, attempt, content[:200])
                if attempt < 3:
                    time.sleep(attempt * 5)
                continue
    else:
        return {
            "region": region_key,
            "region_name": region_name,
            "articles": [],
            "error": last_err,
        }

    articles_out = parsed.get("articles", [])
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
    model: str = "big-pickle",
    max_articles: int = 30,
) -> list[dict]:
    """Summarize articles for all regions using OpenCode Zen (parallel)."""
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
