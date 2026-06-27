# 🏠 분양정보 유망도 추천 시스템

공공데이터포털 OpenAPI와 네이버 부동산 데이터를 활용하여 전국 아파트 분양정보 및 택지정보를 수집하고, 유망도를 점수화하여 주 1회 이메일로 전송하는 Python 자동화 프로그램입니다.

## 주요 기능

- **데이터 수집**: 청약홈, LH, SH, 국토부 실거래가, 네이버 부동산
- **유망도 분석**: 분양가할인율(35%) + 교통/입지(30%) + 브랜드(15%) + 경쟁률(15%) + 규모(5%)
- **리포트 생성**: HTML 이메일 형식 (순위별 하이라이트)
- **자동화**: GitHub Actions 주 1회 실행 + 이메일 전송

## 설치 및 실행

### 로컬 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# Mock 모드 실행 (API 키 없이 테스트)
python main.py --mock all

# CLI 도움말
python main.py --help
```

### 서브커맨드

```bash
python main.py collect --source cheongyak --mock   # 데이터 수집
python main.py analyze --output table --mock       # 유망도 분석
python main.py report --mock                        # 리포트 생성
python main.py --mock all                          # 전체 파이프라인
```

## GitHub Actions 설정

### 필요한 Secrets

GitHub 저장소에서 `Settings → Secrets and variables → Actions`에 다음을 등록하세요:

| Secret | 설명 |
|--------|------|
| `DATA_GO_KR_API_KEY` | 공공데이터포털 API 서비스키 (data.go.kr 회원가입 후 서비스 신청) |
| `EMAIL_USER` | Gmail 주소 (예: `example@gmail.com`) |
| `EMAIL_PASS` | Gmail 앱 비밀번호 (Google 계정 → 보안 → 앱 비밀번호) |
| `EMAIL_TO` | 수신자 이메일 주소 |

### 공공데이터포털 API 신청 방법

1. [data.go.kr](https://www.data.go.kr) 회원가입
2. 아래 서비스 각각 신청 (키 하나로 통합 사용 가능):
   - 청약홈 분양정보 (ID: 15098547)
   - 국토부 아파트 실거래가 (ID: 15126469)
   - LH 분양임대공고문 (ID: 15058530)
   - LH 분양임대공급정보 (ID: 15056765)
   - LH 용지공고내역 (ID: 15072459)
   - SH 분양정보 (ID: 15102880)
3. 마이페이지에서 `serviceKey` 복사 → GitHub Secret에 등록

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
│   │   ├── lh.py                   # LH 수집기
│   │   ├── sh.py                   # SH 수집기
│   │   ├── molit.py                # 국토부 실거래가
│   │   └── naver.py                # 네이버 부동산
│   ├── analyzer/
│   │   ├── __init__.py
│   │   ├── brand_scores.py         # 브랜드 점수
│   │   ├── region_data.py          # 지역/교통 점수
│   │   ├── price_comparator.py     # 할인율 계산
│   │   ├── scorer.py               # 종합 점수 계산
│   │   └── ranker.py               # 순위화
│   ├── reporter/
│   │   ├── __init__.py
│   │   ├── email_renderer.py       # HTML 렌더러
│   │   └── templates/
│   │       └── report.html         # Jinja2 템플릿
│   └── utils/
│       ├── __init__.py
│       ├── api_client.py           # API 클라이언트
│       └── cache.py                # 파일 캐시
├── tests/
│   └── ...                         # pytest 테스트
└── output/
    └── report.html                 # 생성된 리포트
```

## 유망도 점수 기준

| 항목 | 가중치 | 설명 |
|------|--------|------|
| 분양가 할인율 | 35% | 분양가 vs 인근 시세 차이 (20%↑=100점, 0%=50점) |
| 교통/입지 | 30% | 지역별 교통망, 역세권, 수도권 접근성 |
| 시공사 브랜드 | 15% | 건설사 평판 점수 (30+개사) |
| 청약경쟁률 | 15% | 과거 동일 지역 경쟁률 반영 |
| 공급규모 | 5% | 세대수 기반 (1000세대↑=100점) |

## 주의사항

- 본 정보는 참고용이며, 투자 결정은 본인의 판단에 따라 신중히 이루어져야 합니다.
- 특정 상품에 대한 매수 추천이 아닙니다.
- 공공데이터 API는 데이터 지연이 있을 수 있습니다 (최대 1주일).
- 네이버 부동산 데이터는 보조 소스로만 사용됩니다.
