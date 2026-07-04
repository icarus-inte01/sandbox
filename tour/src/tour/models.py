"""데이터 모델 — TourAPI 응답을 표현하는 dataclass 정의."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TourItem:
    """개별 관광정보 항목."""
    content_id: str
    content_type_id: int
    title: str
    addr1: str = ""
    addr2: str = ""
    zipcode: str = ""
    tel: str = ""
    homepage: str = ""
    first_image: str = ""
    first_image2: str = ""
    map_x: float = 0.0
    map_y: float = 0.0
    mlevel: int = 6
    overview: str = ""
    area_code: int = 0
    sigungu_code: int = 0
    cat1: str = ""
    cat2: str = ""
    cat3: str = ""
    created_time: str = ""
    modified_time: str = ""

    @property
    def short_overview(self) -> str:
        """개요를 100자로 제한."""
        if not self.overview:
            return ""
        return self.overview[:100] + ("..." if len(self.overview) > 100 else "")

    @property
    def full_address(self) -> str:
        """전체 주소."""
        if self.addr2:
            return f"{self.addr1} {self.addr2}"
        return self.addr1


@dataclass
class CategoryInfo:
    """카테고리 정의."""
    type_id: int
    name: str
    icon: str = ""


@dataclass
class TourReport:
    """전체 리포트 데이터."""
    region: str
    date: str
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    categories: dict[str, list[TourItem]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화용 dict 변환."""
        return {
            "region": self.region,
            "date": self.date,
            "generated_at": self.generated_at,
            "categories": {
                name: [asdict(item) for item in items]
                for name, items in self.categories.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TourReport":
        """JSON에서 역직렬화."""
        report = cls(region=data["region"], date=data["date"])
        report.generated_at = data.get("generated_at", "")
        categories = {}
        for name, items in data.get("categories", {}).items():
            categories[name] = [TourItem(**item) for item in items]
        report.categories = categories
        return report

    def to_json(self) -> str:
        """JSON 문자열 직렬화."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "TourReport":
        """JSON 문자열에서 역직렬화."""
        return cls.from_dict(json.loads(json_str))


@dataclass
class CacheEntry:
    """캐시 엔트리."""
    key: str
    data: dict[str, Any]
    cached_at: str
    expires_at: str
