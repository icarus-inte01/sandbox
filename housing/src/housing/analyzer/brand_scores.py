"""시공사 브랜드 평판 점수 맵.

주요 건설사/시공사별 평판 점수를 0-100 범위로 매핑합니다.
점수는 시공 품질, 브랜드 인지도, 고객 만족도 등을 종합적으로 고려한 추정치입니다.
"""
from __future__ import annotations

from typing import Optional

# 기본 브랜드 점수 맵
# 점수 기준:
#   90-100: 최상위 대형 건설사 (GS, 현대, 삼성)
#   80-89: 주요 대형 건설사
#   70-79: 중견 건설사
#   60-69: 중소 건설사 / 공기업
#   50-59: 기타
#   0-49: 무명 / 신생
BRAND_SCORES: dict[str, float] = {
    # === TOP 대형 건설사 (90-100) ===
    "GS건설": 95.0,
    "현대건설": 94.0,
    "삼성물산": 96.0,
    "대우건설": 88.0,
    "포스코건설": 90.0,
    "롯데건설": 85.0,
    "대림산업": 87.0,
    "DL이앤씨": 87.0,
    "현대엔지니어링": 89.0,
    "HDC현대산업개발": 84.0,
    "SK에코플랜트": 83.0,
    "GS건설(자이)": 95.0,

    # === 주요 건설사 (75-84) ===
    "호반건설": 80.0,
    "포스코이앤씨": 90.0,
    "한화건설": 78.0,
    "금호건설": 72.0,
    "KCC건설": 75.0,
    "코오롱글로벌": 74.0,
    "태영건설": 70.0,
    "동부건설": 68.0,
    "계룡건설": 72.0,
    "한일건설": 65.0,
    "서희건설": 62.0,
    "반도건설": 70.0,
    "제일건설": 60.0,
    "중흥건설": 76.0,
    "우미건설": 68.0,
    "케이비부동산신탁": 55.0,

    # === 공기업 / 특수법인 (60-75) ===
    "LH": 65.0,
    "LH한국토지주택공사": 65.0,
    "SH공사": 62.0,
    "서울주택도시공사": 62.0,
    "경기도시공사": 60.0,
    "인천도시공사": 60.0,
    "부산도시공사": 60.0,
    "대구도시공사": 60.0,
    "광주도시공사": 58.0,
    "울산도시공사": 58.0,
    "세종도시공사": 58.0,

    # === 기타 ===
    "기타": 50.0,
    "기타건설사": 50.0,
}


def get_brand_score(builder_name: str, overrides: Optional[dict[str, float]] = None) -> float:
    """시공사명으로 브랜드 점수를 조회합니다.

    Args:
        builder_name: 시공사명
        overrides: 개별 오버라이드 점수 맵

    Returns:
        0-100 사이 브랜드 점수
    """
    # 오버라이드 우선
    if overrides and builder_name in overrides:
        return overrides[builder_name]

    # 정확히 일치
    if builder_name in BRAND_SCORES:
        return BRAND_SCORES[builder_name]

    # 부분 일치 검색
    name_lower = builder_name.replace(" ", "").lower()
    for brand, score in BRAND_SCORES.items():
        brand_key = brand.replace(" ", "").lower()
        if brand_key in name_lower or name_lower in brand_key:
            return score

    # 괄호 제거 후 매칭
    simplified = builder_name.split("(")[0].strip()
    if simplified and simplified != builder_name:
        return get_brand_score(simplified, overrides)

    return 50.0  # 기본 중간 점수


def get_brand_score_with_default(
    builder_name: str,
    default: float = 50.0,
    overrides: Optional[dict[str, float]] = None,
) -> float:
    """찾을 수 없는 경우 기본값을 반환하는 버전."""
    if overrides and builder_name in overrides:
        return overrides[builder_name]
    return BRAND_SCORES.get(builder_name, default)
