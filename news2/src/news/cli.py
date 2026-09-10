"""news2 — 국내 언론사 국제부 RSS 기반 뉴스 다이제스트 CLI."""

import argparse
import html
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

from . import email_renderer
from . import rss_fetcher
from . import scoring
from .models import Article


def load_config(config_path: str = "config.yaml") -> dict:
    """설정 파일 로드."""
    path = Path(config_path)
    if not path.exists():
        print(f"설정 파일을 찾을 수 없습니다: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _clean_snippet(snippet: str, limit: int = 200) -> str:
    """RSS description을 한 줄 텍스트로 정리.

    RSS description은 HTML 태그(이미지 썸네일 등)를 포함하는 경우가 많고,
    email_renderer는 마크다운을 줄 단위로 파싱하므로 개행이 남아 있으면
    안 된다. HTML 태그 제거 → 개행을 공백으로 접기 → 길이 제한 순으로 처리한다.
    일부 속보성 기사는 description이 "(" 한 글자뿐인 경우가 있어, 너무 짧은
    텍스트는 의미 없는 것으로 보고 빈 문자열을 반환한다.
    """
    text = re.sub(r"<[^>]+>", " ", snippet)
    text = html.unescape(text)
    text = " ".join(text.split())
    if len(text) < 5:
        return ""
    if len(text) > limit:
        text = text[:limit] + "..."
    return text


def print_articles(articles: list[Article]):
    """콘솔용 텍스트 출력."""
    print(f"\n📰 오늘의 주요 국제뉴스 ({len(articles)}건):\n")
    for i, art in enumerate(articles, 1):
        print(f"  {i}. [{art.source}] {art.title}")
        print(f"     🔗 {art.url}")
        snippet = _clean_snippet(art.snippet) if art.snippet else ""
        if snippet:
            print(f"     📝 {snippet}")
        print()


def format_json_output(articles: list[Article]) -> dict:
    """JSON 출력용 데이터 구성."""
    return {
        "count": len(articles),
        "items": [
            {
                "title": a.title,
                "url": a.url,
                "snippet": a.snippet,
                "source": a.source,
                "published_date": a.published_date,
            }
            for a in articles
        ],
    }


def build_markdown(articles: list[Article]) -> str:
    """email_renderer가 파싱하는 마크다운 포맷으로 변환 (지역 구분 없는 통합 다이제스트)."""
    lines = ["\n# 🌐 오늘의 주요 국제뉴스\n"]

    if not articles:
        lines.append("> 수집된 뉴스 없음\n")
        return "".join(lines)

    for art in articles:
        date_suffix = f" · {art.published_date[:10]}" if art.published_date else ""
        lines.append(f"1. **[{art.title}]({art.url})**{date_suffix}\n")
        snippet = _clean_snippet(art.snippet) if art.snippet else ""
        if snippet:
            lines.append(f"   - **요약**: {snippet}\n")
        lines.append(f"   - **출처**: {art.source}\n")
        lines.append("\n")

    return "".join(lines)


def main():
    """CLI 엔트리포인트."""
    parser = argparse.ArgumentParser(
        prog="news2",
        description="국내 언론사 국제부 RSS 기반 뉴스 다이제스트",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="설정 파일 경로 (기본: config.yaml)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="다이제스트에 포함할 최대 기사 수 (기본: config.yaml의 digest_limit)",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json", "email"],
        default="text",
        help="출력 형식: text, json, 또는 email (HTML 이메일 생성)",
    )
    parser.add_argument(
        "--html-output",
        default="",
        help="Path for HTML output when --output=email (default: news_digest.html).",
    )
    parser.add_argument(
        "--email-url",
        default="",
        help='URL for the "View in browser" link in email output.',
    )

    args = parser.parse_args()

    config = load_config(args.config)
    feeds = config.get("feeds", [])
    limit = args.limit or config.get("digest_limit", 15)

    if not feeds:
        print("config.yaml에 feeds가 정의되어 있지 않습니다.", file=sys.stderr)
        sys.exit(1)

    print(f"📡 국제뉴스 RSS 수집 중... ({len(feeds)}개 매체)", file=sys.stderr)
    all_articles = rss_fetcher.fetch_all(feeds)
    print(f"✅ 총 {len(all_articles)}건 수집", file=sys.stderr)

    selected = scoring.select_top_stories(all_articles, limit)

    if args.output == "json":
        output = format_json_output(selected)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.output == "email":
        md_content = build_markdown(selected)
        html_path = args.html_output or "news_digest.html"

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
        print(f"📧 HTML email saved to: {html_path}", file=sys.stderr)
        print(md_content)
    else:
        print_articles(selected)

    print(f"\n✅ 완료 — 선정된 뉴스 {len(selected)}건 (수집 {len(all_articles)}건 중)")


if __name__ == "__main__":
    main()
