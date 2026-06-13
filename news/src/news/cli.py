import argparse
import logging
import sys

import yaml

from . import fetcher
from . import summarizer as groq_summarizer
from . import gemini_summarizer
from . import zen_summarizer

logger = logging.getLogger(__name__)


def _is_rate_limited(err: str) -> bool:
    err_lower = err.lower()
    return any(k in err_lower for k in ("rate_limit", "429", "resource_exhausted", "quota"))


def _print_text(results: list[dict]):
    for r in results:
        region_name = r.get("region_name", r["region"])
        sep = f"{'═' * 10} {region_name} {'═' * 10}"
        print(f"\n{sep}\n")

        if r.get("error"):
            err = r["error"]
            if _is_rate_limited(err):
                print("[!] ⏳ API 토큰 한도 초과 — 잠시 후 다시 실행하거나 다른 --provider 로 시도")
            else:
                print(f"[!] 요약 생성 실패 - {err}")
            continue

        articles = r.get("articles", [])
        if not articles:
            print("[ ] 수집된 뉴스 없음")
            continue

        for i, art in enumerate(articles, 1):
            title = art.get("title", "")
            url = art.get("url", "")
            one_liner = art.get("one_liner", "")
            significance = art.get("significance", "")
            print(f"{i}. [{title}]")
            print(f"   요약: {one_liner}")
            if significance:
                print(f"   중요도: {significance}")
            print(f"   URL: {url}")
            print()


def _print_markdown(results: list[dict], summarizer_module):
    for r in results:
        region_name = r.get("region_name", r["region"])
        emoji = summarizer_module.emoji_for(r["region"])
        print(f"\n# {emoji} {region_name}\n")

        if r.get("error"):
            err = r["error"]
            if _is_rate_limited(err):
                print("> ⏳ API 토큰 한도 초과 — 잠시 후 다시 실행\n")
            else:
                print(f"> [!CAUTION] 요약 생성 실패 - {err}\n")
            continue

        articles = r.get("articles", [])
        if not articles:
            print("> 수집된 뉴스 없음\n")
            continue

        for art in articles:
            title = art.get("title", "")
            url = art.get("url", "")
            one_liner = art.get("one_liner", "")
            significance = art.get("significance", "")
            print(f"1. **[{title}]({url})**")
            print(f"   - **요약**: {one_liner}")
            if significance:
                print(f"   - **중요도**: {significance}")
            print()


def main():
    parser = argparse.ArgumentParser(
        description="Regional news aggregator — fetch and summarize top stories worldwide."
    )
    parser.add_argument(
        "--regions", "-r",
        type=str,
        default="",
        help="Comma-separated region keys (e.g. asia,europe). Default: all regions.",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=30,
        help="Max articles per region to consider for summarization (default: 30).",
    )
    parser.add_argument(
        "--provider", "-p",
        type=str,
        choices=["groq", "gemini", "zen"],
        default="gemini",
        help="AI provider to use (default: gemini).",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default="",
        help=(
            "Model name. Default: llama-3.3-70b-versatile (groq) "
            "or gemini-2.5-flash-lite (gemini)."
        ),
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="config.yaml",
        help="Path to config file (default: config.yaml).",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        choices=["text", "markdown"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()

    if args.provider == "zen":
        summarizer = zen_summarizer
        default_model = "big-pickle"
        provider_label = "OpenCode Zen"
    elif args.provider == "gemini":
        summarizer = gemini_summarizer
        default_model = "gemini-2.5-flash-lite"
        provider_label = "Gemini"
    else:
        summarizer = groq_summarizer
        default_model = "llama-3.3-70b-versatile"
        provider_label = "Groq"

    model = args.model or default_model

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s | %(message)s")

    print("📡 Fetching news feeds...", file=sys.stderr)
    try:
        all_articles = fetcher.fetch_all_articles(config_path=args.config)
    except Exception as exc:
        print(f"❌ Failed to fetch articles: {exc}", file=sys.stderr)
        sys.exit(1)

    region_names: dict[str, str] = {}
    try:
        with open(args.config, encoding="utf-8") as f:
            raw_cfg = yaml.safe_load(f)
        for key, val in raw_cfg.get("regions", {}).items():
            region_names[key] = val.get("name", key)
    except Exception:
        pass  # fall back to using keys as names

    if args.regions:
        requested = {r.strip() for r in args.regions.split(",") if r.strip()}
        all_articles = {k: v for k, v in all_articles.items() if k in requested}

    total = sum(len(v) for v in all_articles.values())
    print(f"✅ Fetched {total} articles from {len(all_articles)} regions.", file=sys.stderr)

    if not all_articles:
        print("⚠️  No articles fetched. Check your config and network.", file=sys.stderr)
        sys.exit(0)

    print(f"🤖 Summarizing with {provider_label} ({model})...", file=sys.stderr)
    results = summarizer.summarize_all(
        all_articles,
        region_names=region_names,
        model=model,
        max_articles=args.limit,
    )

    print("\n" + "=" * 50)
    print("  World News Digest — Regional Summary")
    print("=" * 50)

    if args.output == "markdown":
        _print_markdown(results, summarizer)
    else:
        _print_text(results)


if __name__ == "__main__":
    main()
