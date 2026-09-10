"""Tavily API를 이용한 뉴스 수집 모듈.

Search 모드: include_answer="advanced"로 AI 요약 포함 결과
Research 모드: /search/research 엔드포인트로 심층 분석 보고서
"""

import time
from typing import List, Optional

from tavily import TavilyClient

from .models import Article, ResearchReport


class TavilyFetcher:
    """Tavily API 뉴스 수집기."""

    def __init__(self, api_key: str):
        self.client = TavilyClient(api_key=api_key)

    def fetch_search(
        self,
        query: str,
        max_results: int = 10,
        region: str = "",
        days: int = 3,
    ) -> tuple[List[Article], str]:
        """Search 엔드포인트로 뉴스 수집.

        Returns:
            (기사 목록, AI 요약 텍스트)
        """
        start = time.time()

        response = self.client.search(
            query=query,
            topic="news",
            max_results=max_results,
            days=days,
            include_answer="advanced",
            search_depth="advanced",
        )

        articles = []
        for item in response.get("results", []):
            articles.append(Article(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                published_date=item.get("published_date", ""),
                source=item.get("source", ""),
                region=region,
                score=item.get("score", 0.0),
            ))

        answer = response.get("answer", "")
        elapsed = time.time() - start
        print(f"  [{region or 'search'}] {len(articles)}건 수집 ({elapsed:.1f}초)")

        return articles, answer

    def fetch_research(
        self,
        query: str,
        region: str = "",
        max_sources: int = 5,
    ) -> ResearchReport:
        """Research 엔드포인트로 심층 분석 보고서 생성.

        Returns:
            ResearchReport (answer + sources + raw_content 포함)
        """
        start = time.time()

        response = self.client.search(
            query=query,
            topic="news",
            max_results=max_sources,
            include_answer="advanced",
            search_depth="advanced",
        )

        # Research 응답 구조: answer + results
        answer = response.get("answer", "")
        results = response.get("results", [])

        sources = [item.get("url", "") for item in results if item.get("url")]
        raw_parts = []
        for item in results:
            title = item.get("title", "")
            content = item.get("content", "")
            url = item.get("url", "")
            raw_parts.append(f"## {title}\n{content}\n[원문: {url}]")
        raw_content = "\n\n".join(raw_parts)

        elapsed = time.time() - start
        print(f"  [{region or 'research'}] 보고서 생성 완료 ({elapsed:.1f}초, {len(sources)}개 소스)")

        return ResearchReport(
            query=query,
            answer=answer,
            sources=sources,
            raw_content=raw_content,
            fetch_time=elapsed,
            region=region,
        )
