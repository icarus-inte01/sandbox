import argparse
import logging
import sys
import tempfile
from pathlib import Path

import yaml

from . import fetcher
from . import groq_summarizer
from . import gemini_summarizer
from . import zen_summarizer
from . import email_renderer
from . import common

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


def _iter_markdown(results: list[dict], summarizer_module):
    """Yield lines of markdown output."""
    for r in results:
        region_name = r.get("region_name", r["region"])
        emoji = summarizer_module.emoji_for(r["region"])
        yield f"\n# {emoji} {region_name}\n"

        if r.get("error"):
            err = r["error"]
            if _is_rate_limited(err):
                yield "> ⏳ API 토큰 한도 초과 — 잠시 후 다시 실행\n"
            else:
                yield f"> [!CAUTION] 요약 생성 실패 - {err}\n"
            continue

        articles = r.get("articles", [])
        if not articles:
            yield "> 수집된 뉴스 없음\n"
            continue

        for art in articles:
            title = art.get("title", "")
            url = art.get("url", "")
            one_liner = art.get("one_liner", "")
            significance = art.get("significance", "")
            yield f"1. **[{title}]({url})**\n"
            yield f"   - **요약**: {one_liner}\n"
            if significance:
                yield f"   - **중요도**: {significance}\n"
            yield "\n"


def _print_markdown(results: list[dict], summarizer_module):
    for line in _iter_markdown(results, summarizer_module):
        print(line, end="")


def _build_markdown(results: list[dict], summarizer_module) -> str:
    return "".join(_iter_markdown(results, summarizer_module))


def _find_empty_regions(results: list[dict]) -> list[str]:
    """Return region keys whose results have 0 articles and no error."""
    return [r["region"] for r in results if not r.get("articles") and not r.get("error")]


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
        choices=["text", "markdown", "email"],
        default="text",
        help="Output format: text, markdown, or email (generates HTML file).",
    )
    parser.add_argument(
        "--html-output",
        type=str,
        default="",
        help="Path for HTML output when --output=email (default: news_digest.html).",
    )
    parser.add_argument(
        "--email-url",
        type=str,
        default="",
        help='URL for the "View in browser" link in email output.',
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Disable cross-provider fallback (default: fallback enabled).",
    )

    args = parser.parse_args()

    # Provider registry: name → (module, default_model, label)
    PROVIDERS: dict[str, tuple] = {
        "zen": (zen_summarizer, "big-pickle", "OpenCode Zen"),
        "gemini": (gemini_summarizer, "gemini-2.5-flash-lite", "Gemini"),
        "groq": (groq_summarizer, "llama-3.3-70b-versatile", "Groq"),
    }
    summarizer, default_model, provider_label = PROVIDERS[args.provider]
    model = args.model or default_model

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s | %(message)s")
    common.reset_timings()

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

    # ── Primary run ──────────────────────────────────────────────────────
    print(f"🤖 Summarizing with {provider_label} ({model})...", file=sys.stderr)
    results = summarizer.summarize_all(
        all_articles,
        region_names=region_names,
        model=model,
        max_articles=args.limit,
    )

    # ── Provider-fallback for empty regions ──────────────────────────────
    if not args.no_fallback:
        fallback_order = [p for p in ("zen", "gemini", "groq") if p != args.provider]
        for fallback_name in fallback_order:
            need_retry = _find_empty_regions(results)
            if not need_retry:
                break
            fallback_mod, fallback_model, fallback_label = PROVIDERS[fallback_name]
            print(
                f"🔁 Retrying {len(need_retry)} empty region(s) with {fallback_label}...",
                file=sys.stderr,
            )
            retry_articles = {k: all_articles[k] for k in need_retry}
            retry_results = fallback_mod.summarize_all(
                retry_articles,
                region_names=region_names,
                model=fallback_model,
                max_articles=args.limit,
            )
            # Merge: keep the original result unless the fallback returned articles
            merged = []
            for orig in results:
                rk = orig["region"]
                fb = next((r for r in retry_results if r["region"] == rk), None)
                if fb and fb.get("articles") and not orig.get("articles"):
                    merged.append(fb)
                else:
                    merged.append(orig)
            results = merged

    header = "\n" + "=" * 50 + "\n  World News Digest — Regional Summary\n" + "=" * 50

    if args.output == "email":
        md_content = _build_markdown(results, summarizer)

        md_path = args.html_output or ""
        if md_path and not md_path.endswith(".html"):
            md_path = md_path  # keep as-is

        html_path = args.html_output or "news_digest.html"

        # Write markdown to a temp file, feed to email renderer
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(md_content)
            tmp_path = tmp.name

        email_renderer.render(
            md_path=tmp_path,
            html_path=html_path,
            run_url=args.email_url,
        )
        Path(tmp_path).unlink(missing_ok=True)
        print(f"\n{'=' * 50}", file=sys.stderr)
        print(f"📧 HTML email saved to: {html_path}", file=sys.stderr)

        # Also print the header + markdown to stdout for preview
        print(header)
        print(md_content)

    elif args.output == "markdown":
        print(header)
        _print_markdown(results, summarizer)
    else:
        print(header)
        _print_text(results)

    if args.verbose:
        common.print_timings()


if __name__ == "__main__":
    main()
