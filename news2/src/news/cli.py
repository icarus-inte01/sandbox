"""news2 — 국내 언론사 국제부 RSS 기반 뉴스 다이제스트 CLI."""

import argparse
import html
import json
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import email_renderer
from . import full_text
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


_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")


def _clean_snippet(snippet: str, limit: int = 280) -> str:
    """RSS description을 한 줄 텍스트로 정리.

    RSS description은 HTML 태그(이미지 썸네일 등)를 포함하는 경우가 많고,
    email_renderer는 마크다운을 줄 단위로 파싱하므로 개행이 남아 있으면
    안 된다. HTML 태그 제거 → 개행을 공백으로 접기 순으로 처리한 뒤,
    limit 글자 근처의 문장 경계(마침표/물음표/느낌표)에서 잘라 문장이
    중간에 뚝 끊기지 않게 한다. 일부 속보성 기사는 description이 "(" 한
    글자뿐인 경우가 있어, 너무 짧은 텍스트는 의미 없는 것으로 보고 빈
    문자열을 반환한다.
    """
    text = re.sub(r"<[^>]+>", " ", snippet)
    text = html.unescape(text)
    text = " ".join(text.split())
    if len(text) < 5:
        return ""
    if len(text) <= limit:
        return text

    # limit 근처(앞뒤 여유 포함)에서 문장 경계를 찾아 완전한 문장으로 마무리
    window = text[: limit + 100]
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(window) if m.end() >= limit * 0.5]
    if ends:
        boundary = next((e for e in ends if e >= limit), ends[-1])
        return window[:boundary].strip()

    return text[:limit].rstrip() + "..."


def enrich_with_full_text(articles: list[Article], max_workers: int = 5) -> None:
    """선정된 기사들의 snippet을 원문 페이지에서 뽑은 본문으로 교체한다.

    RSS 미리보기가 언론사 자체적으로 짧게 잘려있는 경우가 많아, 최종
    선정된 소수(예: 15건)에 한해서만 원문 페이지를 가져와 실제 본문
    앞부분으로 바꾼다. 실패하면 원래 RSS snippet을 그대로 둔다.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        bodies = list(pool.map(lambda a: full_text.fetch_body(a.url), articles))
    for art, body in zip(articles, bodies):
        if body:
            art.snippet = body


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
    parser.add_argument(
        "--no-full-text",
        action="store_true",
        help="선정된 기사 원문 페이지에서 본문을 가져오지 않고 RSS 미리보기만 사용",
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

    if not args.no_full_text:
        print(f"📄 선정된 {len(selected)}건의 원문 본문 추출 중...", file=sys.stderr)
        enrich_with_full_text(selected)

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
