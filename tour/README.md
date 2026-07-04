# 🗺️ 여행 리포트 생성기

한국관광공사 TourAPI(v4.3, KorService2)로 지역별 관광정보를 수집하여 이메일 전송용 HTML 리포트로 만드는 CLI 도구입니다.

## 기능

- **5개 카테고리 수집**: 관광지(12), 음식점(39), 축제/행사(15), 문화시설(14), 숙박(32)
- **상세정보 보강**: 각 항목의 overview(개요), 전화번호, 홈페이지를 추가 API로 보강
- **네이버 지도 링크**: 항목 제목 클릭 시 네이버 지도(이름+좌표)로 연결
- **파일 캐시**: 7일 TTL로 불필요한 API 재호출 방지
- **HTML 리포트**: 이메일 클라이언트 호환 인라인 CSS 스타일
- **GitHub Actions**: workflow_dispatch로 수동 실행, 이메일 발송

## 요구사항

- Python 3.12+
- [TourAPI](https://www.data.go.kr/data/15101578/openapi.do) 서비스 키 (국문 관광정보 서비스)
- 의존성: `requests`, `Jinja2`, `pyyaml`, `premailer`, `pytest`

## 설치

```bash
cd tour
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

환경변수 설정:

```bash
export DATA_GO_KR_API_KEY="발급받은_API_서비스_키"
```

## 사용법

```bash
# 서울 오늘 날짜 리포트
python main.py --region 서울

# 서울 2026-07-11 리포트
python main.py --region 서울 --date 2026-07-11

# 부산 리포트 + 이메일 직접 지정
python main.py --region 부산 --date 2026-08-15 --emails user@example.com

# 캐시 무시하고 새로 수집
python main.py --region 제주 --date 2026-07-30 --no-cache

# 출력 경로 지정
python main.py --region 서울 --date 2026-07-30 --output my-report.html
```

### 인자

| 인자 | 필수 | 설명 | 기본값 |
|------|------|------|--------|
| `--region` | ✅ | 여행 지역 (서울, 부산, 제주 등) | — |
| `--date` | ❌ | 여행 예정일 (YYYY-MM-DD, 미입력시 오늘) | 오늘 날짜 |
| `--emails` | ❌ | 수신 이메일 (쉼표 구분) | config의 EMAIL_TO |
| `--config` | ❌ | 설정 파일 경로 | `config.yaml` |
| `--output` | ❌ | HTML 출력 경로 | `output/report.html` |
| `--no-cache` | ❌ | 캐시 사용 안함 | (사용) |

## 설정 (`config.yaml`)

```yaml
api_keys:
  tour_api: "${DATA_GO_KR_API_KEY}"   # 환경변수 참조

api:
  base_url: "https://apis.data.go.kr/B551011/KorService2"
  max_retries: 2
  timeout: 15
  per_page: 10

cache:
  enabled: true
  ttl_days: 7

sort:
  arrange: "Q"   # Q=수정일순+대표이미지

categories:
  - type_id: 12   # 관광지
  - type_id: 39   # 음식점
  - type_id: 15   # 축제/행사
  - type_id: 14   # 문화시설
  - type_id: 32   # 숙박
```

## GitHub Actions

[`.github/workflows/tour_report.yml`](../.github/workflows/tour_report.yml) (저장소 루트) — workflow_dispatch로 실행:

1. Repository의 **Actions** 탭 → **🗺️ 여행코스 리포트** 선택
2. **Run workflow** → 지역/날짜/이메일 입력
3. 실행 결과가 이메일로 발송됨

### 필요한 Secrets

| 이름 | 설명 |
|------|------|
| `DATA_GO_KR_API_KEY` | TourAPI 서비스 키 |
| `EMAIL_TO` | 기본 수신 이메일 |
| `EMAIL_USER` | Gmail 계정 |
| `EMAIL_PASS` | Gmail 앱 비밀번호 |

## 테스트

```bash
cd tour
python -m pytest tests/ -v
# 38 tests passed
```

## 프로젝트 구조

```
tour/
├── main.py                    # CLI 진입점
├── config.yaml                # 설정 파일
├── requirements.txt           # 의존성
├── pytest.ini                 # pytest 설정
├── src/
│   └── tour/
│       ├── cli.py             # 파이프라인 + argparse
│       ├── api.py             # TourAPIClient (5개 v2 엔드포인트)
│       ├── cache.py           # 파일 기반 TTL 캐시
│       ├── config.py          # YAML 설정 로드
│       ├── models.py          # TourItem, TourReport dataclass
│       ├── region.py          # 17개 지역코드 매핑
│       └── reporter/
│           ├── generator.py   # Jinja2 → HTML 렌더러
│           └── templates/
│               └── report.html.j2  # 이메일 호환 템플릿
├── tests/                     # 38개 pytest
└── (workflow는 저장소 루트 .github/workflows/tour_report.yml)
```
