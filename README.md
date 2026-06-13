# KIS Stock API — 한국투자증권 주식 현재가 조회

한국투자증권(KIS) Open API로 국내/해외 주식 현재가를 조회하는 CLI 도구입니다.

## 기능

- **국내주식 현재가 조회** — 단일 종목, 여러 종목, 포트폴리오 CSV
- **해외주식 현재가 조회** — 티커 직접 입력, 종목명 검색, 포트폴리오 CSV
- **혼합 포트폴리오** (`--mixed`) — 하나의 CSV에 국내+해외 종목을 섞어서 일괄 조회
- **종목명 자동 변환** — 한글/영문 종목명 → 종목코드(국내) 또는 티커(해외)
- **최종 합계 계산** — 해외 평가금액을 원화로 환산하여 합계 표시

## 설정

### API 인증 정보

`~/.config/kis/env` 파일에 아래 내용을 저장하거나 환경변수로 설정합니다:

```
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
```

인증 정보는 다음 우선순위로 조회됩니다:
1. 환경변수 `KIS_APP_KEY` / `KIS_APP_SECRET`
2. `~/.config/kis/env` 파일

API 키는 [KIS Developers](https://apiportal.koreainvestment.com/) 에서 발급받을 수 있습니다.

## 설치

의존 패키지 설치:

```bash
pip install requests
```

## 사용법

### 1. 종목 인덱스 생성 (최초 1회)

각 운영체제/거래소의 마스터 파일을 내려받아 종목명 → 코드 변환에 사용합니다.
생성된 인덱스는 `~/.cache/kis/` 에 캐시됩니다.

```bash
# 국내주식 (KOSPI/KOSDAQ)
python3 kis_stock_api.py --build-index

# 해외주식 (NASDAQ/NYSE/AMEX)
python3 kis_stock_api.py --build-overseas-index
```

> 인덱스가 없어도 티커 직접 입력이나 CSV의 `code` 컬럼 사용시에는 동작합니다.
> 다만 종목명(name)으로 조회하려면 인덱스가 필요합니다.

### 2. 단일/여러 종목 조회

```bash
# 국내주식 — 6자리 숫자 코드
python3 kis_stock_api.py 005930                   # 삼성전자
python3 kis_stock_api.py 005930 000660 373220     # 여러 종목

# 해외주식 — 자동 감지 (6자리 숫자가 아니면 해외)
python3 kis_stock_api.py AAPL                     # 티커 직접 입력
python3 kis_stock_api.py TSLA MSFT NVDA           # 여러 종목

# 회사명 검색 (해외)
python3 kis_stock_api.py "Kinder Morgan"
python3 kis_stock_api.py --overseas "테슬라"       # 한글 이름도 가능
```

### 3. 포트폴리오 CSV 조회

CSV 파일로 보유 종목을 관리하고 일괄 조회합니다.

```bash
# 국내 포트폴리오
python3 kis_stock_api.py -f portfolio.csv

# 해외 포트폴리오
python3 kis_stock_api.py -f portfolio.csv --overseas

# 국내+해외 혼합 (권장)
python3 kis_stock_api.py -f stock.csv --mixed
```

### CSV 형식

`code,qty` 또는 `name,qty` 컬럼을 지원합니다.

```csv
code,qty
005930,100
KMI,50
```

```csv
name,qty
삼성전자,100
Kinder Morgan,50
```

`--mixed` 모드에서는 자동으로 종목을 구분합니다:
- `code`가 6자리 숫자 → 국내주식
- `name`에 한글 포함 → `KOREAN_OVS_MAP` 확인 후 국내/해외 자동 판별
- 영문 이름 → 해외주식 우선, 국내에서 찾아지면 국내 처리
- 실수 수량(소수점) 지원

### 4. 환율 지정

해외 평가금액을 원화로 환산할 때 사용할 환율을 직접 지정할 수 있습니다.
지정하지 않으면 `open.er-api.com` 에서 자동 조회합니다.

```bash
python3 kis_stock_api.py -f stock.csv --mixed --rate 1370
```

## 포트폴리오 예시

`stock.csv`:
```csv
name,qty
삼성전자,1
SK텔레콤,1
킨더 모건,1
QYLD,1
SCHD,1
테슬라,1
```

실행:
```bash
python3 kis_stock_api.py -f stock.csv --mixed
```

출력 예시:
```
=======================================================
  📈 국내주식 포트폴리오
=======================================================
[005930] 삼성전자
  현재가:    360,500 원  x    1주  =    360,500 원
...
───────────────────────────────────────────────────────
                       국내 총 평가금액    1,000,000 원

=======================================================
  🌍 해외주식 포트폴리오
=======================================================
  [NYSE] KMI
  현재가:   31.8050 USD  ...
  평가금액:       31.81 USD
...
───────────────────────────────────────────────────────
                       해외 총 평가금액        140.00 USD

=======================================================
  📊 포트폴리오 최종 합계
=======================================================
                        국내    1,000,000 원
            해외 (USD → KRW)      212,380 원  (환율 1,517원)
───────────────────────────────────────────────────────
                      최종 합계    1,212,380 원
```

## API rate limit

KIS API는 **초당 약 10회** 호출 제한이 있습니다.
- 국내주식: 30종목까지 배치(batch) 조회로 1회 호출에 처리
- 해외주식: 최대 2개 병렬 스레드로 제한하여 rate limit 회피
- rate limit 초과 시(`EGW00201`) 자동 재시도 (2초 대기 후 1회)

## 파일 구조

```
~/.config/kis/env                    — API 인증 정보
~/.cache/kis/stock_code_map.json     — 국내 종목 인덱스 캐시
~/.cache/kis/us_stock_map.json       — 해외 종목 인덱스 캐시

kis_stock_api.py                     — 메인 스크립트
stock.csv / portfolio.csv            — 포트폴리오 CSV
README.md                            — 이 파일
```

## 주의사항

- **장 시작 전/후**에는 API가 정상 응답하지 않을 수 있습니다 (운영시간: 08:30~16:30 KST)
- 모의투자 환경에서는 다른 TR_ID가 필요할 수 있습니다
- 해외주식 조회 시 `search_info`(상품기본정보)는 rate limit으로 인해 포트폴리오에서는 호출하지 않습니다
