"""지역명 → TourAPI 지역코드 매핑."""
from __future__ import annotations

# TourAPI areaCode 매핑
# 출처: 한국관광공사 TourAPI 지역코드
REGION_MAP: dict[str, int] = {
    "서울": 1,
    "서울특별시": 1,
    "서울시": 1,
    "인천": 2,
    "인천광역시": 2,
    "인천시": 2,
    "대전": 3,
    "대전광역시": 3,
    "대전시": 3,
    "대구": 4,
    "대구광역시": 4,
    "대구시": 4,
    "광주": 5,
    "광주광역시": 5,
    "광주시": 5,
    "부산": 6,
    "부산광역시": 6,
    "부산시": 6,
    "울산": 7,
    "울산광역시": 7,
    "울산시": 7,
    "세종": 8,
    "세종특별자치시": 8,
    "세종시": 8,
    "경기": 31,
    "경기도": 31,
    "강원": 32,
    "강원도": 32,
    "강원특별자치도": 32,
    "충북": 33,
    "충청북도": 33,
    "충남": 34,
    "충청남도": 34,
    "경북": 35,
    "경상북도": 35,
    "경남": 36,
    "경상남도": 36,
    "전북": 37,
    "전라북도": 37,
    "전북특별자치도": 37,
    "전남": 38,
    "전라남도": 38,
    "제주": 39,
    "제주도": 39,
    "제주특별자치도": 39,
    # 영문 별칭
    "seoul": 1,
    "busan": 6,
    "jeju": 39,
    "incheon": 2,
    "daegu": 4,
    "daejeon": 3,
    "gwangju": 5,
    "gyeonggi": 31,
    "gangwon": 32,
}


def resolve_region(name: str) -> int:
    """지역명을 TourAPI areaCode로 변환.

    Args:
        name: 지역명 (예: "서울", "부산", "제주도")

    Returns:
        TourAPI areaCode (정수)

    Raises:
        ValueError: 지원하지 않는 지역명인 경우
    """
    cleaned = name.strip().lower()
    # 전체 매핑을 소문자 기준으로 비교
    lower_map = {k.lower(): v for k, v in REGION_MAP.items()}
    if cleaned in lower_map:
        return lower_map[cleaned]
    support_codes: set[int] = {v for v in REGION_MAP.values() if isinstance(v, int)}
    support_names = ", ".join(str(c) for c in sorted(support_codes))
    raise ValueError(
        f"지원하지 않는 지역입니다: '{name}'. 지원 지역 코드: {support_names}"
    )


def get_region_list() -> list[str]:
    """지원하는 대표 지역명 목록 반환."""
    # 대표 이름만 반환 (중복 제거)
    representatives = [
        "서울", "부산", "대구", "인천", "광주", "대전",
        "울산", "세종", "경기", "강원", "충북", "충남",
        "경북", "경남", "전북", "전남", "제주",
    ]
    return representatives
