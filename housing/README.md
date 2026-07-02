# 분양정보 유망도 추천 시스템

공공데이터포털 OpenAPI, vworld.kr, 온비드 공매 데이터를 활용하여 전국 아파트 분양 및 토지(공매 대지) 정보를 수집하고, 유망도를 점수화하여 HTML 이메일 리포트로 제공합니다.

> **상세 설계 문서**: [DESIGN.md](./DESIGN.md)

---

## Quick Start

```bash
# 의존성 설치
pip install -r requirements.txt

# Mock 모드 (API 키 없이 구조 테스트)
python -m src.housing.cli --mock all

# CLI 도움말
python -m src.housing.cli --help
```

---

## Usage

### E2E Pipeline

```bash
# 전체 파이프라인 (수집 → 분석 → 리포트)
python -m src.housing.cli all

# Mock 데이터로 테스트
python -m src.housing.cli --mock all

# 리포트 저장 경로 지정
python -m src.housing.cli all --output /tmp/report.html

# 이메일 발송
# (SMTP_HOST/SMTP_USER/SMTP_PASS/MAIL_TO 환경변수 필요)
python -m src.housing.cli all --send-email
```

### 서브커맨드

```bash
python -m src.housing.cli analyze --output table           # 주택 유망도 분석
python -m src.housing.cli analyze --output table --land    # 토지(대지) 평가
python -m src.housing.cli collect --source cheongyak       # 특정 소스만 수집
python -m src.housing.cli collect --source onbid           # 온비드 공매 대지만
```

---

## Setup

### API 키 발급

1. **공공데이터포털** ([data.go.kr](https://www.data.go.kr/)) 회원가입 후 다음 서비스를 각각 신청 (하나의 키로 통합 사용 가능):
   - 청약홈 분양정보 (ID: 15098547)
   - 국토부 아파트 실거래가 (ID: 15126469)
   - LH 분양임대공고문 (ID: 15058530)
   - 온비드 부동산 물건목록 (ID: B010003)

2. **vworld.kr** ([vworld.kr](https://www.vworld.kr/)) — 토지 평가 시 필요
   - API 키 발급 (`getIndvdLandPriceAttr` 서비스)

### 환경변수

```bash
# 필수 (주택 분석)
export DATA_GO_KR_API_KEY="your_service_key"

# 토지 평가 시 필요
export VWORLD_API_KEY="your_vworld_key"

# 이메일 발송 시 필요
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="your_email@gmail.com"
export SMTP_PASS="your_app_password"
export MAIL_TO="recipient@example.com"
```

### GitHub Actions Secrets

| Secret | 설명 |
|--------|------|
| `DATA_GO_KR_API_KEY` | 공공데이터포털 서비스키 |
| `VWORLD_API_KEY` | vworld.kr API 키 |
| `SMTP_HOST` | SMTP 서버 (기본: smtp.gmail.com) |
| `SMTP_PORT` | SMTP 포트 (기본: 587) |
| `SMTP_USER` | SMTP 계정 |
| `SMTP_PASS` | SMTP 비밀번호 (Gmail 앱 비밀번호) |
| `MAIL_TO` | 수신자 이메일 |

---

## Output

리포트는 `output/report.html`에 저장되며, GitHub Actions 실행 시 아티팩트로 7일간 보관됩니다.

### 리포트 구성

| 섹션 | 내용 | 최대 표시 |
|------|------|:---------:|
| 🏢 **주택 유망도 TOP 20** | 점수순 아파트/공공분양 리스트 | Top 20 |
| 주택형별 상세 | 각 단지의 주택형(면적/분양가) 테이블 | 접이식 |
| 🏗️ **KAMCO 공매 대지** | 온비드 공매 토지 점수순 | Top 30 |
| 📋 **LH 분양용지** | LH 토지/용지 점수순 | Top 30 |

---

## Scoring

### 주택 (아파트 분양)

| 항목 | 가중치 | 데이터 출처 |
|------|:------:|-------------|
| 분양가 할인율 | 35% | 국토부 실거래가 대비 분양가 비교 |
| 교통/입지 | 30% | 지역별 점수 + GTX/지하철 가산 |
| 시공사 브랜드 | 15% | 건설사 평판 점수 (30+개사) |
| 청약경쟁률 | 15% | 과거 경쟁률 매핑 |
| 공급규모 | 5% | 세대수 기반 |

### 토지 (온비드 공매 대지)

| 항목 | 가중치 | 데이터 출처 |
|------|:------:|-------------|
| 공시지가 대비 비율 | 30% | vworld.kr 공시지가 API |
| 감정가 할인율 | 25% | (감정가-입찰가)/감정가 |
| 입지/위치 | 25% | 지역별 입지 점수 |
| 유찰횟수 | 10% | 유찰 많을수록 고득점 |
| 면적 규모 | 10% | 대지 면적 기반 |

---

## Project Structure

```
housing/
├── config.yaml                     # 가중치, API 키, 캐시 설정
├── main.py                         # 진입점
├── requirements.txt                # requests, beautifulsoup4, Jinja2, premailer 등
├── src/housing/
│   ├── cli.py                      # CLI 인터페이스 + E2E 파이프라인
│   ├── config.py                   # YAML → 환경변수 치환 + 타입세이프 접근자
│   ├── models.py                   # SaleListing, TradeRecord 데이터 모델
│   ├── collectors/
│   │   ├── base.py                 # 수집기 기본 클래스
│   │   ├── cheongyak.py            # 청약홈 아파트 분양
│   │   ├── lh.py                   # LH 토지/용지
│   │   ├── onbid.py                # 온비드 공매 대지
│   │   ├── molit.py                # 국토부 아파트 실거래가
│   │   └── sh.py                   # SH 분양 (미사용)
│   ├── analyzer/
│   │   ├── scorer.py               # 주택 종합 점수 계산
│   │   ├── land_scorer.py          # 토지(대지) 평가 + 공시지가 fallback
│   │   ├── ranker.py               # 순위화 (top_n)
│   │   ├── price_comparator.py     # 할인율 계산
│   │   ├── region_data.py          # 지역 점수 + 법정동코드 맵
│   │   └── brand_scores.py         # 브랜드 점수 맵
│   ├── reporter/
│   │   ├── email_renderer.py       # HTML 렌더러 (Jinja2 + premailer)
│   │   └── templates/
│   │       └── report.html         # 이메일 템플릿
│   └── utils/
│       ├── api_client.py           # API 클라이언트 (pagination, rate-limit, retry)
│       └── cache.py                # 파일 캐시 (SHA256 key, TTL)
├── tests/                          # pytest 테스트
└── output/
    └── report.html                 # 생성된 리포트
```

---

## Config

`config.yaml`로 주요 설정을 관리합니다:

```yaml
weights:
  discount_rate: 0.35       # 할인율
  transit_location: 0.30    # 교통/입지
  brand: 0.15               # 브랜드
  competition: 0.15         # 경쟁률
  scale: 0.05               # 규모

api:
  request_delay: 0.1        # API 호출 간격(초)
  max_retries: 3
  timeout: 30

cache:
  enabled: true
  ttl_hours: 6              # 캐시 유효시간
```

---

## Tests

```bash
pytest                          # 전체 테스트
pytest -v                       # 상세 출력
pytest tests/test_scorer.py     # 특정 테스트
```

---

## Notes

- 본 정보는 참고용이며, 투자 결정은 본인의 판단에 따라 신중히 이루어져야 합니다.
- 공공데이터 API는 데이터 지연이 있을 수 있습니다 (최대 1주일).
- vworld.kr 공시지가는 당년도 공시지가이며, 실제 시세와 차이가 있을 수 있습니다.
- 온비드 공매 대지 정보는 실시간 변동될 수 있으므로 입찰 전 반드시 온비드에서 확인하세요.
