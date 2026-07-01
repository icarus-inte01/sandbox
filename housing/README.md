# 🏠 분양정보 유망도 추천 시스템

공공데이터포털 OpenAPI, vworld.kr, 온비드 공매 데이터를 활용하여 전국 아파트 분양정보 및 토지(공매 대지) 정보를 수집하고, 유망도를 점수화하여 HTML 리포트로 제공하는 Python 자동화 프로그램입니다.

## 주요 기능

- **데이터 수집**: 청약홈, LH, 국토부 실거래가, 온비드(공매 대지)
- **주택 유망도 분석**: 분양가할인율(35%) + 교통/입지(30%) + 브랜드(15%) + 경쟁률(15%) + 규모(5%)
- **토지(대지) 평가**: 공시지가(vworld.kr) 대비 입찰가 비율(30%) + 감정가 할인율(25%) + 입지(25%) + 유찰횟수(10%) + 면적(10%)
- **PNU 자동 재구성**: 본번/부번 불완전 PNU를 리스팅 주소 지번에서 추출하여 재조회 → 감정평가액 기반 추정 fallback (100% 커버리지)
- **리포트 생성**: HTML 이메일 형식 — 주택 Top 20 + KAMCO(온비드) + LH 분양용지

## 설치 및 실행

### 로컬 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# Mock 모드 (API 키 없이 구조 테스트)
python main.py all --mock

# CLI 도움말
python main.py --help
```

### 서브커맨드 (실사용)

```bash
python main.py all                              # 전체 파이프라인 (수집→분석→리포트)
python main.py all --output /tmp/report.html    # 리포트 저장 경로 지정
python main.py analyze --output table           # 주택 유망도 분석 (콘솔 출력)
python main.py analyze --output table --land    # 토지(대지) 평가 (콘솔 출력)
python main.py collect --source cheongyak      # 특정 소스만 수집
python main.py collect --source onbid          # 온비드 공매 대지만 수집
```

### 환경변수

| 변수 | 필수 | 설명 |
|------|------|------|
| `DATA_GO_KR_API_KEY` | 주택분석시 | 공공데이터포털 API 서비스키 |
| `VWORLD_API_KEY` | 토지평가시 | vworld.kr API 서비스키 (토지공시지가 조회) |

## GitHub Actions 설정

### 필요한 Secrets

GitHub 저장소에서 `Settings → Secrets and variables → Actions`에 다음을 등록하세요:

| Secret | 필수 | 설명 |
|--------|------|------|
| `DATA_GO_KR_API_KEY` | 주택분석시 | 공공데이터포털 API 서비스키 (data.go.kr) |
| `VWORLD_API_KEY` | 토지평가시 | vworld.kr API 서비스키 |
| `EMAIL_USER` | 이메일전송시 | Gmail 주소 (예: `example@gmail.com`) |
| `EMAIL_PASS` | 이메일전송시 | Gmail 앱 비밀번호 |
| `EMAIL_TO` | 이메일전송시 | 수신자 이메일 주소 |

### API 신청 방법

**공공데이터포털** ([data.go.kr](https://www.data.go.kr)):
1. 회원가입 후 아래 서비스 각각 신청 (키 하나로 통합 사용 가능):
   - 청약홈 분양정보 (ID: 15098547)
   - 국토부 아파트 실거래가 (ID: 15126469)
   - LH 분양임대공고문 (ID: 15058530) — 토지(01) + 분양주택(05) 통합
   - LH 분양임대공급정보 (ID: 15056765)
2. 마이페이지에서 `serviceKey` 복사 → GitHub Secret에 등록

**vworld.kr** ([vworld.kr](https://www.vworld.kr)):
1. 회원가입 → API 키 발급 (`getIndvdLandPriceAttr` 서비스)
2. 발급받은 키를 GitHub Secret `VWORLD_API_KEY`에 등록 / 로컬 환경변수에 설정

### 워크플로우 실행

- **자동**: 매주 월요일 09:00 KST
- **수동**: GitHub Actions 탭에서 `workflow_dispatch` 트리거

## 프로젝트 구조

```
housing/
├── main.py                         # 진입점
├── config.yaml                     # 설정 파일
├── requirements.txt                # 의존성
├── pytest.ini                      # pytest 설정
├── README.md                       # 문서
├── .github/workflows/
│   └── weekly_report.yml           # GitHub Actions
├── src/housing/
│   ├── __init__.py
│   ├── cli.py                      # CLI 인터페이스
│   ├── config.py                   # 설정 로더
│   ├── models.py                   # 데이터 모델
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py                 # 수집기 기본 클래스
│   │   ├── cheongyak.py            # 청약홈 수집기
│   │   ├── lh.py                   # LH 분양용지/주택 수집기
│   │   ├── molit.py                # 국토부 실거래가
│   │   ├── naver.py                # 네이버 부동산 (mock only)
│   │   ├── onbid.py                # 온비드 공매 대지 수집기
│   │   └── sh.py                   # SH 분양정보 (미사용)
│   ├── analyzer/
│   │   ├── __init__.py
│   │   ├── brand_scores.py         # 브랜드 점수
│   │   ├── region_data.py          # 지역/교통 점수
│   │   ├── price_comparator.py     # 할인율 계산
│   │   ├── scorer.py               # 주택 종합 점수 계산
│   │   ├── ranker.py               # 순위화
│   │   └── land_scorer.py          # 토지(대지) 평가 — vworld.kr 공시지가 기반
│   ├── reporter/
│   │   ├── __init__.py
│   │   ├── email_renderer.py       # HTML 렌더러
│   │   └── templates/
│   │       └── report.html         # Jinja2 템플릿 (주택+KAMCO+LH 섹션)
│   └── utils/
│       ├── __init__.py
│       ├── api_client.py           # API 클라이언트 (페이지네이션, 재시도)
│       └── cache.py                # 파일 캐시 (TTL 기반)
├── tests/
│   └── ...                         # pytest 테스트
└── output/
    └── report.html                 # 생성된 리포트
```

## 유망도 점수 기준

### 주택 (아파트 분양)

| 항목 | 가중치 | 설명 |
|------|--------|------|
| 분양가 할인율 | 35% | 분양가 vs 인근 시세 차이 (20%↑=100점, 0%=50점) |
| 교통/입지 | 30% | 지역별 교통망, 역세권, 수도권 접근성 |
| 시공사 브랜드 | 15% | 건설사 평판 점수 (30+개사) |
| 청약경쟁률 | 15% | 과거 동일 지역 경쟁률 반영 |
| 공급규모 | 5% | 세대수 기반 (1000세대↑=100점) |

### 토지 (온비드 공매 대지)

| 항목 | 가중치 | 설명 |
|------|--------|------|
| 공시지가 대비 비율 | 30% | 입찰가 ÷ vworld.kr 공시지가 (낮을수록 고득점) |
| 감정가 할인율 | 25% | (감정가 - 입찰가) ÷ 감정가 |
| 입지/위치 | 25% | 지역별 입지 점수 (수도권/광역시/기타) |
| 유찰횟수 | 10% | 유찰 많을수록 고득점 (할인 기대) |
| 면적 규모 | 10% | 대지 면적 기반 (클수록 고득점) |

### 토지 공시지가 조회 fallback

| 단계 | 방법 | 성공률 |
|------|------|--------|
| 1차 | vworld.kr `getIndvdLandPriceAttr` API 직접 조회 | ~89% |
| 2차 | PNU 본번/부번=0000 → 리스팅 주소 지번 추출 → 재조회 | +10% |
| 3차 | 감정평가액 × 0.7 ÷ 면적으로 공시지가 추정 | +1% |
| **합계** | | **100%** |

## 주의사항

- 본 정보는 참고용이며, 투자 결정은 본인의 판단에 따라 신중히 이루어져야 합니다.
- 특정 상품에 대한 매수 추천이 아닙니다.
- 공공데이터 API는 데이터 지연이 있을 수 있습니다 (최대 1주일).
- vworld.kr 공시지가는 당년도 공시지가이며, 실제 시세와 차이가 있을 수 있습니다.
- 온비드 공매 대지 정보는 실시간 변동될 수 있으므로 입찰 전 반드시 온비드에서 확인하세요.
