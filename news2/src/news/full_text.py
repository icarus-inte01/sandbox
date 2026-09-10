"""선정된 기사의 원문 페이지에서 본문 앞부분을 추출하는 모듈.

RSS/메타태그의 미리보기 텍스트는 언론사가 자체적으로 짧게 잘라서 내보내는
경우가 많아(예: "..."/"···"로 끝나는 티저), 최종 선정된 기사에 한해 원문
페이지를 가져와 실제 본문 문단을 추출한다. 언론사마다 페이지 구조가 달라
언제든 깨질 수 있으므로, 실패하면 항상 빈 문자열을 반환해 호출부가 RSS
스니펫으로 폴백할 수 있게 한다.
"""

import logging
import re
import urllib.request

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# 알려진 언론사 본문 컨테이너 (있으면 여기서만 문단을 뽑아 관련기사 위젯 등
# 본문과 무관한 내용이 섞이는 것을 막는다). 없으면 문서 전체에서 추출한다.
_CONTAINER_SELECTORS = [
    {"id": "articleWrap"},        # 연합뉴스
    {"class_": "art_body"},       # 경향신문
    {"class_": "article-body"},   # 한국경제
    {"class_": "article-text"},   # 한겨레
]

_BOILERPLATE_RE = re.compile(
    r"무단전재|재배포\s*금지|저작권자|All rights reserved|ⓒ|구독|재판매\s*및\s*DB\s*금지|"
    r"기자$|Google\s*검색|네이버에서|구독하기|카카오톡|"
    r"(로이터|AFP|AP|EPA|dpa|게티이미지|텐아시아)\s*연합뉴스\s*$"
)
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")


def _candidate_segments(scope) -> list[str]:
    """스코프 내에서 문단 후보 텍스트 목록을 뽑는다.

    대부분 언론사는 본문을 <p> 태그로 감싸므로 각 <p>를 독립된 문단으로
    다룬다(사진 설명 등 짧은 문단을 개별적으로 걸러내기 위함). 일부(한국경제
    등)는 <br>로만 구분한 텍스트 노드를 그대로 쓰는데, 이 경우 <br>가 줄바꿈
    표시일 뿐 문장 중간에 걸쳐 있을 수 있으므로 통째로 하나의 문단으로 보고
    나중에 문장 경계에서 자른다(조각내면 문장이 반토막날 수 있음).
    """
    paras = scope.find_all("p")
    if paras:
        return [p.get_text(" ", strip=True) for p in paras]
    return [scope.get_text(" ", strip=True)]


def _trim_to_sentence(text: str, target_len: int) -> str:
    """target_len 근처의 문장 경계(마침표 등)에서 잘라 문장이 중간에 끊기지 않게 한다."""
    if len(text) <= target_len:
        return text
    window = text[: target_len + 150]
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(window) if m.end() >= target_len * 0.5]
    if ends:
        boundary = next((e for e in ends if e >= target_len), ends[-1])
        return window[:boundary].strip()
    return text[:target_len].rstrip() + "..."


def _extract(html_text: str, min_len: int, target_len: int) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup.select("script, style, aside, figure, figcaption, nav, header, footer, noscript, ins"):
        tag.decompose()

    container = None
    for sel in _CONTAINER_SELECTORS:
        container = soup.find(**sel)
        if container:
            break
    scope = container or soup

    kept: list[str] = []
    total = 0
    for text in _candidate_segments(scope):
        text = " ".join(text.split())
        if len(text) < min_len or _BOILERPLATE_RE.search(text):
            continue
        kept.append(text)
        total += len(text)
        if total >= target_len + 150:
            break

    combined = " ".join(kept)
    return _trim_to_sentence(combined, target_len)


def fetch_body(url: str, min_len: int = 20, target_len: int = 280, timeout: float = 10.0) -> str:
    """기사 원문 페이지에서 본문 앞부분을 가져온다. 실패 시 빈 문자열 반환."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": _UA, "Accept-Language": "ko-KR,ko;q=0.9"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return _extract(raw, min_len, target_len)
    except Exception as exc:
        logger.warning("본문 추출 실패 %s: %s", url, exc)
        return ""
