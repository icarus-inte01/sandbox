"""CLI 인터페이스 — argparse 기반 명령행 인자 처리."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Any

from src.tour.api import TourAPIClient
from src.tour.cache import TourCache
from src.tour.config import load_config
from src.tour.models import TourItem, TourReport
from src.tour.region import resolve_region
from src.tour.reporter.generator import ReportGenerator


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """명령행 인자 파싱.

    Args:
        argv: 인자 리스트 (기본: sys.argv[1:])

    Returns:
        파싱된 인자
    """
    parser = argparse.ArgumentParser(
        description="🗺️ 여행 코스 자동 생성기 — TourAPI 기반 지역 관광정보 리포트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""사용 예:
  python main.py --region 서울                      # 오늘 날짜
  python main.py --region 서울 --date 2026-07-11
  python main.py --region 부산 --date 2026-08-15 --emails user@example.com
  python main.py --region 제주 --date 2026-07-30 --no-cache --output my-report.html
        """,
    )

    parser.add_argument(
        "--region",
        required=True,
        help="여행 지역 (예: 서울, 부산, 제주)",
    )
    parser.add_argument(
        "--date",
        required=False,
        default="",
        help="여행 예정일 (YYYY-MM-DD 형식, 미입력시 오늘 날짜)",
    )
    parser.add_argument(
        "--emails",
        required=False,
        default="",
        help="수신 이메일 주소 (쉼표 구분, 미입력시 config의 EMAIL_TO 사용)",
    )
    parser.add_argument(
        "--config",
        required=False,
        default="config.yaml",
        help="설정 파일 경로 (기본: config.yaml)",
    )
    parser.add_argument(
        "--output",
        required=False,
        default="output/report.html",
        help="HTML 출력 경로 (기본: output/report.html)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="캐시 무시하고 API 직접 호출",
    )

    args = parser.parse_args(argv)
    return args


def validate_args(args: argparse.Namespace) -> None:
    """인자 유효성 검증.

    Args:
        args: 파싱된 인자

    Raises:
        SystemExit: 유효성 검증 실패시
    """
    if not args.date:
        args.date = datetime.now().strftime("%Y-%m-%d")
    # 날짜 형식 검증
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(
            f"오류: 날짜 형식이 올바르지 않습니다. "
            f"YYYY-MM-DD 형식으로 입력해주세요. (입력값: {args.date})",
            file=sys.stderr,
        )
        sys.exit(1)

    # 지역 유효성 검증
    try:
        resolve_region(args.region)
    except ValueError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)


def build_tour_item(raw: dict[str, Any]) -> TourItem:
    """TourAPI 응답 데이터를 TourItem으로 변환."""
    return TourItem(
        content_id=str(raw.get("contentid", "")),
        content_type_id=int(raw.get("contenttypeid", 0) or 0),
        title=raw.get("title", ""),
        addr1=raw.get("addr1", ""),
        addr2=raw.get("addr2", ""),
        zipcode=raw.get("zipcode", ""),
        tel=raw.get("tel", ""),
        homepage=raw.get("homepage", ""),
        first_image=raw.get("firstimage", ""),
        first_image2=raw.get("firstimage2", ""),
        map_x=float(raw.get("mapx", 0) or 0),
        map_y=float(raw.get("mapy", 0) or 0),
        mlevel=int(raw.get("mlevel", 6) or 6),
        overview=raw.get("overview", ""),
        area_code=int(raw.get("areacode", 0) or 0),
        sigungu_code=int(raw.get("sigungucode", 0) or 0),
        cat1=raw.get("cat1", ""),
        cat2=raw.get("cat2", ""),
        cat3=raw.get("cat3", ""),
        created_time=str(raw.get("createdtime", "")),
        modified_time=str(raw.get("modifiedtime", "")),
    )


_INTRO_TEL_FIELDS: dict[int, str] = {
    12: "infocenter",          # 관광지
    14: "infocenterculture",   # 문화시설
    28: "infocenterleports",   # 레포츠
    32: "infocenterlodging",   # 숙박
    38: "infocenter",          # 쇼핑
    39: "infocenterfood",      # 음식점
}


def _intro_tel(intro: dict[str, Any], content_type_id: int) -> str:
    field = _INTRO_TEL_FIELDS.get(content_type_id)
    if not field:
        return ""
    val = intro.get(field, "")
    return str(val).strip() if val else ""


def enrich_item_detail(
    client: TourAPIClient,
    item: TourItem,
) -> TourItem:
    """상세정보로 TourItem 보강 (overview, image, homepage, tel)."""
    if not item.overview or not item.first_image:
        try:
            detail = client.fetch_detail(item.content_id, item.content_type_id)
            if detail:
                if not item.overview:
                    item.overview = detail.get("overview", "")
                if not item.first_image:
                    item.first_image = detail.get("firstimage", "")
                if not item.first_image2:
                    item.first_image2 = detail.get("firstimage2", "")
                if not item.homepage:
                    item.homepage = detail.get("homepage", "")
        except Exception:
            pass

    if not item.tel:
        try:
            intro = client.fetch_intro(item.content_id, item.content_type_id)
            if intro:
                tel = _intro_tel(intro, item.content_type_id)
                if tel:
                    item.tel = tel
        except Exception:
            pass

    return item


def main(argv: list[str] | None = None) -> int:
    """전체 파이프라인 실행.

    Args:
        argv: 명령행 인자

    Returns:
        종료 코드 (0=성공)
    """
    args = parse_args(argv)
    validate_args(args)

    print(f"🗺️ 여행 리포트 생성 시작")
    print(f"   지역: {args.region}")
    print(f"   날짜: {args.date}")
    print(f"   출력: {args.output}")
    print()

    # 설정 로드
    config = load_config(args.config)
    print(f"✅ 설정 로드 완료")

    # 지역 코드 변환
    area_code = resolve_region(args.region)
    print(f"✅ 지역 코드: {args.region} → {area_code}")

    # 캐시 설정
    cache = None
    if not args.no_cache and config.cache.get("enabled", True):
        cache = TourCache(
            cache_dir=config.get_cache_dir(),
            ttl_days=config.get_cache_ttl_days(),
        )
        print(f"✅ 캐시 사용 (TTL: {config.get_cache_ttl_days()}일)")

    # API 클라이언트
    api_key = config.api_keys.get("tour_api", "")
    if not api_key:
        print("오류: DATA_GO_KR_API_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 1

    client = TourAPIClient(api_key, config, cache=cache)
    print(f"✅ TourAPI 클라이언트 초기화 완료")
    print()

    # 카테고리별 데이터 수집
    categories = config.get_categories()
    sort_order = config.get_sort_order()
    report = TourReport(region=args.region, date=args.date)

    date_compact = args.date.replace("-", "")

    for cat in categories:
        type_id = cat["type_id"]
        name = cat["name"]
        icon = cat.get("icon", "")
        print(f"  [{icon}] {name} 데이터 수집 중...")

        try:
            if type_id == 15:
                # 축제/행사는 날짜 기반 검색
                items_raw = client.fetch_festivals(
                    area_code=area_code,
                    event_start_date=date_compact,
                    num_rows=config.get_api_setting("per_page", 10),
                )
            else:
                # 일반 카테고리는 지역 기반 조회
                items_raw = client.fetch_by_region(
                    area_code=area_code,
                    content_type_id=type_id,
                    arrange=sort_order,
                    num_rows=config.get_api_setting("per_page", 10),
                )

            # TourItem으로 변환
            tour_items = [build_tour_item(raw) for raw in items_raw]

            for i, item in enumerate(tour_items):
                tour_items[i] = enrich_item_detail(client, item)

            report.categories[name] = tour_items
            print(f"    → {len(tour_items)}개 항목 수집 완료")

        except Exception as e:
            print(f"    ⚠️ 수집 실패: {e}")
            report.categories[name] = []

    print()
    print(f"✅ 모든 데이터 수집 완료")
    print()

    # HTML 리포트 생성
    generator = ReportGenerator()
    html = generator.render(report)
    generator.save_html(html, args.output)
    print(f"✅ HTML 리포트 저장 완료: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
