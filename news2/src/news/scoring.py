"""크로스피드 스코어링: 여러 매체가 함께 다루는 이슈를 중요 뉴스로 판단."""

import re

from .models import Article


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


def _word_jaccard(a: str, b: str) -> float:
    """두 문자열의 단어 집합 자카드 유사도 (0.0 ~ 1.0)."""
    wa = set(re.sub(r"[^\w]", " ", a.lower()).split())
    wb = set(re.sub(r"[^\w]", " ", b.lower()).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _cross_feed_score(art: Article, groups: dict[str, list[Article]]) -> int:
    """이 기사와 비슷한 제목을 다루는 '다른' 매체 수."""
    nkey = _norm_title(art.title)
    score = 0
    for src, arts in groups.items():
        if src == art.source:
            continue
        for other in arts:
            if _word_jaccard(nkey, _norm_title(other.title)) > 0.35:
                score += 1
                break
    return score


def select_top_stories(articles: list[Article], n: int, similarity_threshold: float = 0.35) -> list[Article]:
    """전체 기사 풀에서 중요한(여러 매체가 함께 다루는) 순으로 최대 n건을 선정한다.

    1. source(매체)별로 그룹화하고, 기사마다 다른 매체에서도 다루는지(cross_feed_score) 계산.
    2. 점수 내림차순 → 최신순으로 정렬.
    3. 순서대로 채택하되, 이미 채택한 기사와 제목이 비슷한(유사도 > threshold) 기사는
       같은 사건을 다룬 것으로 보고 건너뛴다 (동일 사건이 여러 번 나오는 것 방지).
    """
    groups: dict[str, list[Article]] = {}
    for art in articles:
        groups.setdefault(art.source, []).append(art)

    scored = [(_cross_feed_score(art, groups), art) for art in articles]
    scored.sort(key=lambda x: (x[0], x[1].published_date), reverse=True)

    selected: list[Article] = []
    for _score, art in scored:
        nkey = _norm_title(art.title)
        if any(_word_jaccard(nkey, _norm_title(s.title)) > similarity_threshold for s in selected):
            continue
        selected.append(art)
        if len(selected) >= n:
            break

    return selected
