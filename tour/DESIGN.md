# 설계 문서

## 아키텍처 개요

```
사용자 입력 (CLI args)
     │
     ▼
  cli.main()          ← argparse + 파이프라인 오케스트레이션
     │
     ├─► config.load_config()    ← YAML 설정 로드 + 환경변수 치환
     ├─► TourCache               ← 파일 기반 7일 TTL 캐시
     ├─► TourAPIClient           ← TourAPI v4.3 (KorService2) HTTP 클라이언트
     │    ├─ areaBasedList2      → 지역+콘텐츠타입별 목록
     │    ├─ searchFestival2     → 날짜+지역별 축제 검색
     │    ├─ detailCommon2       → contentId로 개요/이미지 보강
     │    └─ detailIntro2        → contentId+typeId로 전화번호 보강
     │
     ├─► build_tour_item()       ← API 응답 → TourItem 변환
     ├─► enrich_item_detail()    ← 상세정보 보강 (2회 추가 API 호출)
     │
     └─► ReportGenerator         ← Jinja2 템플릿 → 이메일 호환 HTML
          └─ report.html.j2      ← 인라인 CSS, 네이버 지도 링크
```

## 모듈 책임

### `main.py`
CLI 진입점. `PYTHONPATH=src` 필요. `src.tour.cli.main()` 호출.

### `src/tour/cli.py`
파이프라인 오케스트레이션 담당:
- `parse_args()` / `validate_args()` — 인자 파싱 및 검증
- `build_tour_item()` — API 응답 dict → `TourItem` dataclass 변환 (빈 문자열 `int('')` 방어 로직 포함)
- `enrich_item_detail()` — `detailCommon2`(overview) + `detailIntro2`(tel) 순차 호출, 실패해도 진행
- `main()` — 전체 파이프라인 실행: 설정→지역코드→캐시→API클라이언트→카테고리별수집→보강→HTML생성

### `src/tour/api.py`
`TourAPIClient` — 실제 HTTP 통신:
- `_request()` — 재시도(exponential backoff), 타임아웃, 응답코드 검증
- `_extract_items()` — TourAPI 응답 구조에서 `items` 추출 (빈 문자열 방어)
- `fetch_by_region()` — `areaBasedList2` (지역+콘텐츠타입별)
- `fetch_festivals()` — `searchFestival2` (날짜+지역별)
- `fetch_detail()` — `detailCommon2` (contentId로 개요 보강)
- `fetch_intro()` — `detailIntro2` (contentId+typeId로 전화번호 보강)
- 모든 enrichment 메서드에 캐싱 적용

### `src/tour/cache.py`
파일 기반 TTL 캐시:
- 키 → SHA256 → 파일명, JSON 직렬화
- `cached_at` / `expires_at` 타임스탬프 검증
- 7일 기본 TTL

### `src/tour/config.py`
YAML 설정 로드:
- `${ENV_VAR}` 패턴 → 환경변수 치환
- `api_keys`, `api`, `cache`, `sort`, `categories` 섹션

### `src/tour/models.py`
데이터 모델:
- `TourItem` — dataclass, 20개 필드, `short_overview`/`full_address` 프로퍼티
- `TourReport` — region + date + categories dict, JSON 직렬화 지원
- `CacheEntry` — 캐시 메타데이터

### `src/tour/region.py`
지역명 → 지역코드 매핑 (17개 시/도):
- 명칭 유연 매칭: `서울`, `서울시`, `서울특별시` → 1
- `resolve_region()` — ValueError throw on unknown

### `src/tour/reporter/generator.py`
`ReportGenerator`:
- Jinja2 `Environment` 초기화
- `render()` — TourReport → HTML 문자열 (카테고리별 데이터 구성, context 생성)
- `save_html()` — 파일 저장

## 데이터 흐름

```
1. 사용자 입력: --region "서울" --date "2026-07-11"
2. 지역코드 변환: "서울" → 1
3. 설정 로드: config.yaml (정렬 Q, 5개 카테고리)
4. 카테고리 루프:
   ┌─ 일반(12,39,14,32): fetch_by_region(areaCode=1, contentTypeId=N)
   │    → areaBasedList2 응답
   │    → build_tour_item() 변환
   │    → enrich_item_detail() — 상위 10개 detailCommon2 + detailIntro2
   │    → report.categories[name] = tour_items
   │
   └─ 축제(15): fetch_festivals(areaCode=1, eventStartDate=20260711)
        → searchFestival2 응답
        → build_tour_item() 변환
        → enrich_item_detail() — 상위 10개 보강
        → report.categories[name] = tour_items

5. ReportGenerator.render(report) → HTML
6. HTML 저장
```

## TourAPI v4.3 (KorService2) 대응

### 이전 버전(v1/v3)과의 차이

| 항목 | 이전 (KorService1) | 현재 (KorService2 v4.3) |
|------|-------------------|------------------------|
| base URL | HTTP | **HTTPS 필수** |
| 엔드포인트 | `areaBasedList1` | `areaBasedList2` |
| 상세정보 | `defaultYN`, `overviewYN` 등 YN 파라미터 | **모두 제거됨**, `contentId`만 전송 |
| contentTypeId | detailCommon의 필수 파라미터 | **제거됨** (전송시 500 오류) |
| 정렬 `O` | 인기순 | **제목순** (의미 변경됨) |

### 알려진 이슈

- **detailCommon2 빈 응답**: 일부 contentId는 overview가 없음 (`items: ""`). `_extract_items()`에서 방어.
- **searchFestival2 빈 결과**: 해당 기간/지역에 축제 없을 시 `items: ""` 문자열 응답.
- **areaBasedList2 일부 필드 누락**: `sigungucode`, `mlevel`이 빈 문자열로 오는 경우 있음 → `build_tour_item()`에서 `or 0` / `or 6` 방어.

## 캐시 전략

```
cache_key = f"area-{area_code}-type-{content_type_id}-page-{page_no}"
           or f"festival-area-{area_code}-date-{event_start_date}-page-{page_no}"
           or f"enrich-detailCommon2-{content_id}-t{type_id}"
           or f"enrich-detailIntro2-{content_id}-t{type_id}"
```

- 파일 경로: `.cache/{sha256_hash}.json`
- TTL: 7일 (configurable)
- `--no-cache` 플래그로 전체 캐시 우회 가능
- enrichment 호출(detailCommon2, detailIntro2)도 캐싱되어 중복 API 호출 방지

## 테스트

38개 pytest (`tests/`):
- `test_api.py` — mock 기반 API 호출 시나리오
- `test_cache.py` — 저장/조회/만료/덮어쓰기
- `test_region.py` — 17개 지역 매핑 + 오류 케이스
- `test_reporter.py` — HTML 렌더링 + 커스텀 템플릿
- `conftest.py` — 공통 fixture (mock response, cache, config)

```bash
python -m pytest tests/ -v
```
