"""분양정보 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SupplyType(Enum):
    """분양유형."""
    APT = "apt"               # 아파트 분양
    PUBLIC = "public"         # 공공분양/행복주택
    LAND = "land"             # 택지/용지
    SH = "sh"                 # SH 분양
    OFFICETEL = "officetel"   # 오피스텔/도시형생활주택
    OTHER = "other"           # 기타


class SaleStatus(Enum):
    """분양상태."""
    PLANNED = "planned"       # 분양예정
    OPEN = "open"             # 청약중
    CLOSED = "closed"         # 청약마감
    UNSOLD = "unsold"         # 미분양


@dataclass
class SaleListing:
    """분양 매물 단일 건.

    모든 수집기는 이 모델로 데이터를 변환하여 반환합니다.
    """
    name: str                             # 주택/단지명
    region: str                           # 공급 위치 (시/도 + 시/군/구)
    supply_type: SupplyType = SupplyType.OTHER  # 분양유형
    status: SaleStatus = SaleStatus.PLANNED     # 분양상태
    units: int = 0                        # 공급세대수
    price: int = 0                        # 분양금액 (만원 단위)
    market_price: int = 0                 # 인근 실거래가 참고가 (만원 단위)
    builder: str = ""                     # 시공사/건설사
    supply_purpose: str = ""              # 공급용도 (토지: 점포겸용/준주거/근린생활시설용지 등)
    pyeong_type: str = ""                 # 주택형/전용면적 정보
    competition_rate: float = 0.0         # 청약경쟁률
    move_in_date: str = ""                # 입주예정월
    announcement_date: str = ""           # 모집공고일
    region_code: str = ""                 # 공급지역코드
    source: str = ""                      # 데이터 출처 (cheongyak/lh/molit/naver)
    raw_data: dict = field(default_factory=dict)  # 원본 데이터
    units_info: list[dict] = field(default_factory=list)  # 주택형별 상세 [(model_no, house_type, supply_area, price, households), ...]

    # 분석 결과 필드 (analyzer에서 채움)
    discount_rate: Optional[float] = None  # 분양가 할인율 (%)
    transit_score: Optional[float] = None  # 교통/입지 점수
    brand_score: Optional[float] = None    # 브랜드 점수
    competition_score: Optional[float] = None  # 경쟁률 점수
    scale_score: Optional[float] = None    # 규모 점수
    total_score: Optional[float] = None    # 종합 유망도 점수


@dataclass
class TradeRecord:
    """실거래가 기록.

    국토부 실거래가 API 응답을 저장합니다.
    """
    apartment_name: str            # 아파트명
    price: int                     # 거래금액 (만원)
    area: float                    # 전용면적 (㎡)
    contract_date: str             # 계약일 (YYYYMM)
    floor: int                     # 층
    build_year: int                # 건축년도
    region_code: str               # 법정동코드
    region_name: str               # 지역명
