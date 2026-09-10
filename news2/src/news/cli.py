"""news2 — Tavily 기반 뉴스 수집 CLI."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import yaml

from .tavily_fetcher import TavilyFetcher
from .models import Article, ResearchReport
from . import email_renderer

REGION_EMOJI = {
    "asia": "🌏",
    "europe": "🌍",
    "north_america": "🌎",
    "south_america": "🌎",
    "africa": "🌍",
    "oceania": "🌏",
    "middle_east": "🕌",
    "general": "🌐",
}


def load_config(config_path: str = "config.yaml") -> dict:
    """설정 파일 로드."""
    path = Path(config_path)
    if not path.exists():
        print(f"설정 파일을 찾을 수 없습니다: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_search_results(articles: list[Article], answer: str, region: str):
    """Search 모드 결과 출력."""
    print(f"\n{'='*60}")
    print(f"  📍 {region.upper()}")
    print(f"{'='*60}")

    if answer:
        print(f"\n🤖 AI 요약:\n{answer}\n")

    if articles:
        print(f"📰 뉴스 ({len(articles)}건):\n")
        for i, art in enumerate(articles, 1):
            print(f"  {i}. {art.title}")
            print(f"     🔗 {art.url}")
            if art.snippet:
                snippet = art.snippet[:150] + ("..." if len(art.snippet) > 150 else "")
                print(f"     📝 {snippet}")
            print()
    else:
        print("  (수집된 뉴스 없음)\n")


def print_research_report(report: ResearchReport):
    """Research 모드 결과 출력."""
    print(f"\n{'='*60}")
    print(f"  📊 Research 보고서 — {report.region.upper()}")
    print(f"{'='*60}")
    print(f"  ⏱️  소요시간: {report.fetch_time:.1f}초")
    print(f"  🔗 소스: {report.source_count}개\n")

    if report.answer:
        print(f"🤖 분석 보고서:\n{report.answer}\n")

    if report.sources:
        print("📚 참고 소스:")
        for i, src in enumerate(report.sources, 1):
            print(f"  {i}. {src}")
        print()


def _build_markdown(search_results: list[tuple[list[Article], str, str]]) -> str:
    """Search 결과를 email_renderer가 파싱하는 마크다운 포맷으로 변환.

    Tavily의 answer(자체 LLM 생성 요약)는 사용하지 않고, 기사 원문 스니펫만 사용한다.
    """
    lines = []
    for articles, _answer, region in search_results:
        emoji = REGION_EMOJI.get(region, "🌐")
        region_label = region.replace("_", " ").title()
        lines.append(f"\n# {emoji} {region_label}\n")

        if not articles:
            lines.append("> 수집된 뉴스 없음\n")
            continue

        for art in articles:
            date_suffix = f" · {art.published_date}" if art.published_date else ""
            lines.append(f"1. **[{art.title}]({art.url})**{date_suffix}\n")
            snippet = art.snippet[:200] + ("..." if len(art.snippet) > 200 else "")
            if snippet:
                lines.append(f"   - **요약**: {snippet}\n")
            lines.append("\n")

    return "".join(lines)


def format_json_output(
    search_results: list[tuple[list[Article], str, str]],
    research_results: list[ResearchReport],
) -> dict:
    """JSON 출력용 데이터 구성."""
    output = {"articles": [], "research": []}

    for articles, answer, region in search_results:
        output["articles"].append({
            "region": region,
            "answer": answer,
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
        })

    for report in research_results:
        output["research"].append({
            "region": report.region,
            "query": report.query,
            "answer": report.answer,
            "sources": report.sources,
            "fetch_time": report.fetch_time,
        })

    return output


def main():
    """CLI 엔트리포인트."""
    parser = argparse.ArgumentParser(
        prog="news2",
        description="Tavily 기반 뉴스 수집기",
    )
    parser.add_argument(
        "--mode",
        choices=["search", "research"],
        default="search",
        help="수집 모드: search(빠른검색) 또는 research(심층분석)",
    )
    parser.add_argument(
        "--regions",
        nargs="*",
        help="수집할 지역 (예: asia europe). 미지정 시 config 기본값 사용",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="설정 파일 경로 (기본: config.yaml)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="지역당 최대 결과 수 (search 모드)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 형식으로 출력 (--output json 과 동일, 하위호환용)",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json", "email"],
        default="text",
        help="출력 형식: text, json, 또는 email (HTML 이메일 생성, search 모드 전용)",
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
        "--query",
        help="Research 모드에서 사용할 커스텀 쿼리",
    )

    args = parser.parse_args()

    # API 키 확인
    import os
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        print("TAVILY_API_KEY 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        sys.exit(1)

    # 설정 로드
    config = load_config(args.config)
    regions_config = config.get("regions", {})

    # 대상 지역 결정
    if args.regions:
        target_regions = args.regions
        use_general = False
    else:
        target_regions = config.get("default_regions", list(regions_config.keys()))
        use_general = not args.query  # 지역 미지정 + 쿼리 미지정 → 일반 뉴스

    # Fetcher 초기화
    fetcher = TavilyFetcher(api_key)

    search_results = []
    research_results = []

    print(f"\n🚀 뉴스 수집 시작 — 모드: {args.mode}")

    if use_general:
        # 일반 뉴스 1회 호출
        general_query = args.query or "major global news today"
        print(f"   쿼리: {general_query} (1회 호출)")

        if args.mode == "search":
            articles, answer = fetcher.fetch_search(
                query=general_query,
                max_results=args.max_results,
                region="general",
            )
            search_results.append((articles, answer, "general"))
        elif args.mode == "research":
            report = fetcher.fetch_research(query=general_query, region="general")
            research_results.append(report)
    else:
        # 지역별 호출
        print(f"   대상 지역: {', '.join(target_regions)} ({len(target_regions)}회 호출)")

        if args.mode == "search":
            for region in target_regions:
                if region not in regions_config:
                    print(f"  ⚠️  알 수 없는 지역: {region} (건너뜀)", file=sys.stderr)
                    continue

                query = regions_config[region]["query"]
                articles, answer = fetcher.fetch_search(
                    query=query,
                    max_results=args.max_results,
                    region=region,
                )
                search_results.append((articles, answer, region))

        elif args.mode == "research":
            for region in target_regions:
                if args.query:
                    query = args.query
                elif region in regions_config:
                    query = regions_config[region]["query"]
                else:
                    print(f"  ⚠️  알 수 없는 지역: {region} (건너뜀)", file=sys.stderr)
                    continue

                report = fetcher.fetch_research(query=query, region=region)
                research_results.append(report)

    # 출력
    output_mode = "json" if args.json else args.output

    if output_mode == "json":
        output = format_json_output(search_results, research_results)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output_mode == "email":
        if args.mode != "search":
            print("⚠️  --output email은 --mode search에서만 지원됩니다.", file=sys.stderr)
            sys.exit(1)

        md_content = _build_markdown(search_results)
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
        if args.mode == "search":
            for articles, answer, region in search_results:
                print_search_results(articles, answer, region)
        elif args.mode == "research":
            for report in research_results:
                print_research_report(report)

    # 요약
    total_articles = sum(len(arts) for arts, _, _ in search_results)
    total_research = len(research_results)
    print(f"\n✅ 완료 — 뉴스 {total_articles}건, 보고서 {total_research}건")


if __name__ == "__main__":
    main()
