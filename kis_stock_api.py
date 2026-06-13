"""
한국투자증권 KIS Open API — 국내/해외 주식 현재가 REST 조회

사용법:
  # ~/.config/kis/env 파일에 App Key / Secret 저장 (KEY=VALUE 형식)
  #   KIS_APP_KEY=your_app_key
  #   KIS_APP_SECRET=your_app_secret
  #
  # 또는 환경변수로 직접 설정:
  #   export KIS_APP_KEY="your_app_key"
  #   export KIS_APP_SECRET="your_app_secret"

  python kis_stock_api.py 005930                # 국내 단일 조회
  python kis_stock_api.py 005930 000660         # 국내 여러 종목
  python kis_stock_api.py --build-index         # 국내 종목 인덱스 생성
  python kis_stock_api.py -f portfolio.csv      # 포트폴리오 (code,qty / name,qty)

  # 해외주식 (자동감지: 6자리 숫자가 아니면 해외주식)
  python kis_stock_api.py KMI                   # 티커 직접 조회
  python kis_stock_api.py AAPL MSFT TSLA        # 여러 종목
  python kis_stock_api.py -f portfolio.csv --overseas  # 해외 포트폴리오

  # 해외주식 (종목명 → 티커 변환)
  python kis_stock_api.py --build-overseas-index       # US 종목 인덱스 생성
  python kis_stock_api.py "Kinder Morgan" --overseas   # 종목명 검색 조회
"""

import os
import csv
import json
import re
import time
import ssl
import difflib
import argparse
import zipfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests


MST_CACHE = Path.home() / ".cache" / "kis" / "stock_code_map.json"
MST_URLS = {
    "kospi": "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
    "kosdaq": "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
}

# ── 해외주식 (US) 종목 인덱스 ──────────────────────────────────────

OVS_CACHE = Path.home() / ".cache" / "kis" / "us_stock_map.json"

# NASDAQ Trader FTP — 미국 전체 상장종목 목록
NASDAQ_LISTED_URL = "ftp://ftp.nasdaqtrader.com/symboldirectory/nasdaqlisted.txt"
OTHER_LISTED_URL = "ftp://ftp.nasdaqtrader.com/symboldirectory/otherlisted.txt"

# 해외주식 거래소코드/상품유형코드 매핑 (KIS API)
OVS_EXCHANGE_MAP: dict[str, tuple[str, str]] = {
    "NASDAQ": ("NAS", "512"),
    "NYSE":   ("NYS", "513"),
    "AMEX":   ("AMS", "529"),
}

# otherlisted.txt 의 Exchange 컬럼 값 → KIS 거래소코드
OVS_EXCH_COL_MAP: dict[str, str] = {
    "N": "NYSE",
    "A": "AMEX",
    "P": "AMEX",       # NYSE Arca → KIS AMS (529)
    "Z": "NASDAQ",     # BATS → NAS
    "V": "NASDAQ",     # IEX → NAS
}

# 한글 해외주식 종목명 → 티커 매핑 (KIS API search_info 로 확인된 것들)
KOREAN_OVS_MAP: dict[str, str] = {
    "킨더 모건": "KMI",
    "킨더모건": "KMI",
    "쿠팡": "CPNG",
    "테슬라": "TSLA",
    "애플": "AAPL",
    "마이크로소프트": "MSFT",
    "아마존": "AMZN",
    "구글": "GOOGL",
    "알파벳": "GOOGL",
    "엔비디아": "NVDA",
    "엔디비아": "NVDA",
    "메타": "META",
    "브로드컴": "AVGO",
    "비스토": "VSTO",
    "팔란티어": "PLTR",
    "ARM 홀딩스": "ARM",
    "ARM": "ARM",
    "도요타": "TM",
    "혼다": "HMC",
}


def _download_and_parse_mst(url: str) -> dict[str, str]:
    """MST 파일을 다운로드해 이름→코드 매핑을 반환한다."""
    ssl._create_default_https_context = ssl._create_unverified_context
    zip_path = Path("/tmp", f"kis_mst_{hash(url)}.zip")
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        mst_name = next(n for n in zf.namelist() if n.endswith(".mst"))
        raw = zf.read(mst_name).decode("cp949")
    zip_path.unlink(missing_ok=True)

    mapping: dict[str, str] = {}
    for line in raw.splitlines():
        if len(line) < 30:
            continue
        code = line[:9].strip()
        name = line[21 : len(line) - 228].strip()
        if code and name:
            mapping[name] = code
            mapping[name.replace(" ", "")] = code
    return mapping


def _build_stock_code_map() -> dict[str, str]:
    """로컬 캐시를 확인하고 없으면 MST를 내려받아 이름→코드 매핑을 만든다."""
    if MST_CACHE.exists():
        try:
            data = json.loads(MST_CACHE.read_text())
            if isinstance(data, dict) and len(data) > 1000:
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    mapping: dict[str, str] = {}
    for market, url in MST_URLS.items():
        try:
            mapping.update(_download_and_parse_mst(url))
            print(f"[MST] {market} 종목정보 로드 완료")
        except Exception as e:
            print(f"[MST] {market} 로드 실패 — {e}")

    if not mapping:
        raise RuntimeError("종목코드 마스터 파일을 내려받을 수 없습니다.")

    MST_CACHE.parent.mkdir(parents=True, exist_ok=True)
    MST_CACHE.write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
    print(f"[MST] {len(mapping)}개 종목 매핑 캐시 완료")
    return mapping


# ── 해외주식 종목 인덱스 다운로드 ─────────────────────────────────


def _download_text_file(url: str) -> str:
    """URL에서 텍스트 파일을 다운로드한다 (FTP/HTTP 지원)."""
    ssl._create_default_https_context = ssl._create_unverified_context
    tmp = Path(f"/tmp/kis_ovs_{hash(url)}.txt")
    urllib.request.urlretrieve(url, tmp)
    text = tmp.read_text("utf-8", errors="replace")
    tmp.unlink(missing_ok=True)
    return text


def _build_overseas_stock_map() -> dict[str, dict]:
    """
    미국 상장종목 전체 목록을 NASDAQ Trader 에서 내려받아
    {이름: {ticker, exchange, product_type}} 매핑을 만든다.
    """
    if OVS_CACHE.exists():
        try:
            data = json.loads(OVS_CACHE.read_text())
            if isinstance(data, dict) and len(data) > 1000:
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    mapping: dict[str, dict] = {}

    # 1. NASDAQ listed
    try:
        raw = _download_text_file(NASDAQ_LISTED_URL)
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("Symbol") or "File Creation Time" in line or line.startswith("|"):
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            ticker = parts[0].strip()
            cname = parts[1].strip()
            if ticker and cname:
                entry = {"ticker": ticker, "exchange": "NAS", "product_type": "512"}
                mapping[cname] = entry
                mapping[cname.replace(" ", "")] = entry
                mapping[cname.upper()] = entry
                mapping[cname.upper().replace(" ", "")] = entry
                mapping[ticker.upper()] = entry
        print(f"[NASDAQ] {len(mapping)} 종목 로드")
    except Exception as e:
        print(f"[NASDAQ] 로드 실패 — {e}")

    # 2. NYSE / AMEX / Other listed
    try:
        raw = _download_text_file(OTHER_LISTED_URL)
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("NASDAQ Symbol") or "File Creation Time" in line or line.startswith("|"):
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            ticker = parts[0].strip()
            cname = parts[1].strip()
            exch_col = parts[2].strip()
            exchange_name = OVS_EXCH_COL_MAP.get(exch_col)
            if not exchange_name or not ticker or not cname:
                continue
            kis_exch, prdt_type = OVS_EXCHANGE_MAP[exchange_name]
            entry = {"ticker": ticker, "exchange": kis_exch, "product_type": prdt_type}
            mapping[cname] = entry
            mapping[cname.replace(" ", "")] = entry
            mapping[cname.upper()] = entry
            mapping[cname.upper().replace(" ", "")] = entry
            mapping[ticker.upper()] = entry
        print(f"[NYSE/AMEX] +{len(mapping)} 종목")
    except Exception as e:
        print(f"[NYSE/AMEX] 로드 실패 — {e}")

    if not mapping:
        raise RuntimeError("해외주식 종목정보를 내려받을 수 없습니다.")

    OVS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    OVS_CACHE.write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
    print(f"[OVS] {len(mapping)}개 해외종목 매핑 캐시 완료")
    return mapping


def resolve_overseas_stock_name(
    name: str, ovs_map: dict[str, dict]
) -> tuple[str, str, str]:
    """
    회사명 또는 티커로 해외주식 정보를 찾는다.

    Returns
    -------
    (ticker, exchange_code, product_type_code)
    """
    raw = name.strip().upper()
    cleaned = raw.replace(" ", "")

    entry = ovs_map.get(raw) or ovs_map.get(cleaned)
    if entry:
        return entry["ticker"], entry["exchange"], entry["product_type"]

    # fuzzy match
    candidates = difflib.get_close_matches(raw, ovs_map, n=1, cutoff=0.6)
    if not candidates:
        candidates = difflib.get_close_matches(cleaned, ovs_map, n=1, cutoff=0.6)
    if candidates:
        matched = candidates[0]
        entry = ovs_map[matched]
        print(f"  ⚠️  '{name}' → '{matched}' ({entry['ticker']}) 으로 유사매칭")
        return entry["ticker"], entry["exchange"], entry["product_type"]

    raise ValueError(
        f"해외주식을 찾을 수 없습니다: '{name}'\n"
        f"  --build-overseas-index 를 먼저 실행했는지 확인하세요."
    )


def resolve_overseas_stock_ticker(
    ticker_or_name: str, ovs_map: dict[str, dict] | None
) -> tuple[str, str, str]:
    """
    입력이 대문자 1~5자리 티커처럼 보이면 그대로 반환하고,
    아니라면 이름→티커 변환을 시도한다.

    Returns (ticker, exchange, product_type)
    """
    cleaned = ticker_or_name.strip().upper()
    # Ticker pattern: 1-5 alphanumeric (with optional . or - for share classes)
    if re.match(r'^[A-Z0-9.]{1,5}$', cleaned):
        if ovs_map and cleaned in ovs_map:
            e = ovs_map[cleaned]
            return e["ticker"], e["exchange"], e["product_type"]
        # 티커를 알지만 맵에 없으면 기본 NYSE 추정 + search_info 로 확인
        return cleaned, "NYS", "513"

    # 한글 종목명 매핑 확인
    korean_ticker = KOREAN_OVS_MAP.get(ticker_or_name.strip()) or KOREAN_OVS_MAP.get(cleaned)
    if korean_ticker:
        if ovs_map and korean_ticker in ovs_map:
            e = ovs_map[korean_ticker]
            return e["ticker"], e["exchange"], e["product_type"]
        return korean_ticker, "NYS", "513"

    if ovs_map:
        return resolve_overseas_stock_name(ticker_or_name, ovs_map)
    raise ValueError(
        f"티커 또는 종목명을 입력하세요. (예: KMI / 'Kinder Morgan')\n"
        f"  --build-overseas-index 로 US 종목 인덱스를 먼저 생성하세요."
    )


def resolve_stock_name(name: str, code_map: dict[str, str]) -> str:
    raw = name.strip()
    cleaned = raw.replace(" ", "")
    code = code_map.get(raw) or code_map.get(cleaned)
    if code:
        return code
    if cleaned.isdigit():
        return cleaned
    close = difflib.get_close_matches(raw, code_map, n=1, cutoff=0.7)
    if not close:
        close = difflib.get_close_matches(cleaned, code_map, n=1, cutoff=0.7)
    if close:
        matched_name = close[0]
        matched_code = code_map[matched_name]
        print(f"  ⚠️  '{raw}' → '{matched_name}' ({matched_code}) 으로 유사매칭")
        return matched_code
    raise ValueError(f"종목명을 찾을 수 없습니다: '{name}'")


@dataclass
class PortfolioItem:
    code: str
    qty: float
    name: str = ""


def load_portfolio(path: str | Path, code_map: dict[str, str] | None = None) -> list[PortfolioItem]:
    items: list[PortfolioItem] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV 파일이 비어 있습니다.")
        col_names = {c.strip().lower() for c in reader.fieldnames}

        has_code = "code" in col_names
        has_name = "name" in col_names

        if not has_code and not has_name:
            raise ValueError(
                "CSV에 'code' 또는 'name' 컬럼이 필요합니다.\n"
                "  예) code,qty 또는 name,qty"
            )

        for row in reader:
            qty_raw = row.get("qty", "").strip()
            if not qty_raw:
                continue
            try:
                qty = float(qty_raw)
            except ValueError:
                raise ValueError(f"qty 값이 숫자가 아닙니다: '{qty_raw}'")
            if qty <= 0:
                raise ValueError(f"qty는 0보다 커야 합니다: {qty}")

            code = row.get("code", "").strip()
            name = row.get("name", "").strip()

            if code:
                items.append(PortfolioItem(code=code, qty=qty, name=name))
            elif name and code_map is not None:
                resolved = resolve_stock_name(name, code_map)
                items.append(PortfolioItem(code=resolved, qty=qty, name=name))
            elif name:
                raise ValueError(
                    f"종목명을 코드로 변환하려면 --build-index 를 먼저 실행하세요.\n"
                    f"  python kis_stock_api.py --build-index"
                )
            else:
                raise ValueError("각 행에 'code' 또는 'name' 값이 필요합니다.")
    if not items:
        raise ValueError("CSV 파일에 유효한 종목이 없습니다.")
    return items


KST = timezone(timedelta(hours=9))

ENV_FILE = Path.home() / ".config" / "kis" / "env"


def _load_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def _get_credential(key: str) -> str:
    val = os.environ.get(key)
    if val:
        return val
    env = _load_env_file()
    val = env.get(key)
    if val:
        return val
    raise RuntimeError(
        f"{key} 를 찾을 수 없습니다.\n"
        f"  ~/.config/kis/env 파일에 {key}=값 을 추가하거나\n"
        f"  export {key}=값 으로 환경변수를 설정해주세요."
    )


class KISClient:
    """한국투자증권 Open API REST 클라이언트"""

    BASE_URL = "https://openapi.koreainvestment.com:9443"

    def __init__(
        self,
        app_key: str | None = None,
        app_secret: str | None = None,
        token_cache_file: str | Path | None = None,
    ):
        self.app_key = app_key or _get_credential("KIS_APP_KEY")
        self.app_secret = app_secret or _get_credential("KIS_APP_SECRET")
        self._session = requests.Session()

        if token_cache_file:
            self._token_cache = Path(token_cache_file)
        else:
            self._token_cache = Path.home() / ".kis_token_cache.json"

        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ── 토큰 ──────────────────────────────────────────────────────────

    def _load_cached_token(self) -> bool:
        """로컬 캐시에서 아직 유효한 토큰을 불러온다."""
        if not self._token_cache.exists():
            return False
        try:
            data = json.loads(self._token_cache.read_text())
            self._token = data["access_token"]
            self._token_expires_at = data["expires_at"]
            if time.time() < self._token_expires_at - 60:
                return True
        except (KeyError, json.JSONDecodeError):
            pass
        return False

    def _save_token(self, access_token: str, expires_in: int):
        self._token = access_token
        self._token_expires_at = time.time() + expires_in
        self._token_cache.parent.mkdir(parents=True, exist_ok=True)
        self._token_cache.write_text(
            json.dumps(
                {
                    "access_token": access_token,
                    "expires_at": self._token_expires_at,
                    "saved_at": datetime.now(KST).isoformat(),
                },
                indent=2,
            )
        )

    def _issue_token(self) -> str:
        """신규 토큰 발급 (POST /oauth2/tokenP)."""
        resp = self._session.post(
            f"{self.BASE_URL}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"토큰 발급 실패 ({resp.status_code}): {resp.text}"
            )
        body = resp.json()
        token = body["access_token"]
        expires_in = body.get("expires_in", 86400)
        self._save_token(token, expires_in)
        print(
            f"[KIS] 토큰 발급 완료 — {expires_in}초 유효 (만료: "
            f"{datetime.fromtimestamp(time.time() + expires_in, KST).isoformat()})"
        )
        return token

    def get_token(self) -> str:
        """유효 토큰 반환 (캐시 → 발급)."""
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        if self._load_cached_token():
            return self._token  # type: ignore
        return self._issue_token()

    # ── 종목 구분 ─────────────────────────────────────────────────────

    @staticmethod
    def _market_code(stock_code: str) -> str:
        """종목코드 첫글자로 시장 구분."""
        return "Q" if stock_code.startswith("10") else "J"

    # ── 현재가 조회 ──────────────────────────────────────────────────

    def inquire_price(self, stock_code: str) -> dict:
        """
        국내주식 현재가 조회.

        Parameters
        ----------
        stock_code : str
            6자리 종목코드 (예: "005930" 삼성전자)

        Returns
        -------
        dict
            API 응답 output 객체 (stck_prpr, prdy_vrss, prdy_ctrt, …)
        """
        token = self.get_token()
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010100",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": self._market_code(stock_code),
            "FID_INPUT_ISCD": stock_code,
        }
        resp = self._session.get(
            f"{self.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=headers,
            params=params,
        )
        body = resp.json()
        msg_code = body.get("msg_cd", "")
        if msg_code != "MCA00000":
            raise RuntimeError(
                f"현재가 조회 실패 ({msg_code}): {body.get('msg1', '')}"
            )
        return body["output"]

    # ── 여러 종목 한 번에 ────────────────────────────────────────────

    def inquire_prices(self, *stock_codes: str) -> list[dict]:
        """여러 종목 현재가를 순차 조회해 리스트로 반환."""
        return [self.inquire_price(code) for code in stock_codes]

    def inquire_prices_batch(self, *stock_codes: str) -> dict[str, dict]:
        """
        관심종목(멀티종목) 시세조회 API로 최대 30종목을 한 번에 조회.

        Returns
        -------
        dict[str, dict]
            {종목코드: {stck_prpr, prdy_vrss, prdy_ctrt, …}} 형태의 매핑
        """
        token = self.get_token()
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST11300006",
        }

        results: dict[str, dict] = {}
        for chunk_start in range(0, len(stock_codes), 30):
            chunk = stock_codes[chunk_start : chunk_start + 30]
            params: dict[str, str] = {}
            for i, code in enumerate(chunk):
                params[f"FID_COND_MRKT_DIV_CODE_{i+1}"] = self._market_code(code)
                params[f"FID_INPUT_ISCD_{i+1}"] = code

            resp = self._session.get(
                f"{self.BASE_URL}/uapi/domestic-stock/v1/quotations/intstock-multprice",
                headers=headers,
                params=params,
            )
            body = resp.json()
            msg_code = body.get("msg_cd", "")
            if msg_code != "MCA00000":
                raise RuntimeError(
                    f"멀티종목 조회 실패 ({msg_code}): {body.get('msg1', '')}"
                )
            for item in body.get("output", []):
                code = item.get("inter_shrn_iscd", "")
                results[code] = {
                    "stck_prpr": item.get("inter2_prpr"),
                    "prdy_vrss": item.get("inter2_prdy_vrss"),
                    "prdy_ctrt": item.get("prdy_ctrt"),
                    "prdy_vrss_sign": item.get("prdy_vrss_sign"),
                    "stck_oprc": item.get("inter2_oprc"),
                    "stck_hgpr": item.get("inter2_hgpr"),
                    "stck_lwpr": item.get("inter2_lwpr"),
                    "acml_vol": item.get("acml_vol"),
                    "hts_kor_isnm": item.get("inter_kor_isnm"),
                    "prdt_name": item.get("inter_kor_isnm"),
                }
        return results

    # ── 해외주식 현재체결가 ─────────────────────────────────────────

    def overseas_inquire_price(self, exchange: str, ticker: str) -> dict:
        """
        해외주식 현재체결가 조회 (HHDFS00000300).

        Parameters
        ----------
        exchange : str
            거래소코드 (NAS / NYS / AMS / HKS / TSE …)
        ticker : str
            종목 티커 (AAPL, KMI, …)

        Returns
        -------
        dict
            API 응답 output (last, rate, vol, …)
        """
        token = self.get_token()
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "HHDFS00000300",
        }
        params = {"AUTH": "", "EXCD": exchange, "SYMB": ticker}
        resp = self._session.get(
            f"{self.BASE_URL}/uapi/overseas-price/v1/quotations/price",
            headers=headers,
            params=params,
        )
        body = resp.json()
        msg_code = body.get("msg_cd", "")
        if msg_code not in ("MCA00000",) and not msg_code.startswith("KIOK"):
            raise RuntimeError(
                f"해외주식 현재가 조회 실패 ({msg_code}): {body.get('msg1', '')}"
            )
        return body["output"]

    # ── 해외주식 상품기본정보 ───────────────────────────────────────

    def overseas_search_info(self, product_type: str, ticker: str) -> dict:
        """
        해외주식 상품기본정보 조회 (CTPF1702R).

        Parameters
        ----------
        product_type : str
            상품유형코드 (512=NASDAQ, 513=NYSE, 529=AMEX, …)
        ticker : str
            종목코드

        Returns
        -------
        dict
            기업명, 시장구분 등 기본정보
        """
        token = self.get_token()
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "CTPF1702R",
        }
        params = {"PRDT_TYPE_CD": product_type, "PDNO": ticker}
        resp = self._session.get(
            f"{self.BASE_URL}/uapi/overseas-price/v1/quotations/search-info",
            headers=headers,
            params=params,
        )
        body = resp.json()
        msg_code = body.get("msg_cd", "")
        if msg_code not in ("MCA00000",) and not msg_code.startswith("KIOK"):
            raise RuntimeError(
                f"해외주식 상품정보 조회 실패 ({msg_code}): {body.get('msg1', '')}"
            )
        return body["output"]

    # ── 해외주식 현재가상세 ─────────────────────────────────────────

    def overseas_inquire_price_detail(self, exchange: str, ticker: str) -> dict:
        """
        해외주식 현재가상세 조회 (HHDFS76200200).

        Parameters
        ----------
        exchange : str
            거래소코드 (NAS / NYS / AMS …)
        ticker : str
            종목 티커
        """
        token = self.get_token()
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "HHDFS76200200",
        }
        params = {"AUTH": "", "EXCD": exchange, "SYMB": ticker}
        resp = self._session.get(
            f"{self.BASE_URL}/uapi/overseas-price/v1/quotations/price-detail",
            headers=headers,
            params=params,
        )
        body = resp.json()
        msg_code = body.get("msg_cd", "")
        if msg_code not in ("MCA00000",) and not msg_code.startswith("KIOK"):
            raise RuntimeError(
                f"해외주식 현재가상세 조회 실패 ({msg_code}): {body.get('msg1', '')}"
            )
        return body["output"]


# ── 포맷팅 ─────────────────────────────────────────────────────────────


def format_overseas_price(ticker: str, exchange: str, data: dict) -> str:
    """해외주식 현재체결가 포맷팅 (USD)."""
    last = data.get("last", "-")
    rate = data.get("rate", "-")
    diff = data.get("diff", "-")
    vol = data.get("tvol", "-")
    val = data.get("tamt", "-")
    base = data.get("base", "-")
    exch_name = {"NAS": "NASDAQ", "NYS": "NYSE", "AMS": "AMEX"}.get(exchange, exchange)

    sign_map = {"1": "", "2": "+", "3": "", "4": "-", "5": "-"}
    sign = sign_map.get(data.get("sign", ""), "")
    return (
        f"  [{exch_name}] {ticker}\n"
        f"  현재가: {last:>10} USD\n"
        f"  전일대비: {sign}{diff:>10} ({rate:>8}%)\n"
        f"  전일종가: {base:>10} USD\n"
        f"  거래량: {vol}  |  거래대금: {val}"
    )


def format_overseas_search_info(ticker: str, data: dict) -> str:
    """해외주식 상품기본정보 포맷팅."""
    name_kor = data.get("prdt_name", "-")
    name_eng = data.get("prdt_eng_name", "-")
    market = data.get("tr_mket_name", data.get("ovrs_excg_name", "-"))
    return (
        f"  종목명: {name_kor}\n"
        f"  영문명: {name_eng}\n"
        f"  티커:   {ticker}\n"
        f"  시장:   {market}"
    )


# ── CLI (기존) ─────────────────────────────────────────────────────────


def format_price(data: dict) -> str:
    stck_prpr = data.get("stck_prpr", "-")
    prdy_vrss = data.get("prdy_vrss", "-")
    prdy_ctrt = data.get("prdy_ctrt", "-")
    acml_vol = data.get("acml_vol", "-")
    stck_hgpr = data.get("stck_hgpr", "-")
    stck_lwpr = data.get("stck_lwpr", "-")
    stck_oprc = data.get("stck_oprc", "-")

    sign = "+" if not prdy_vrss.startswith("-") and prdy_vrss != "0" else ""
    return (
        f"  현재가: {stck_prpr:>8} 원\n"
        f"  전일대비: {sign}{prdy_vrss:>8} 원 ({prdy_ctrt:>7}%)\n"
        f"  시가/고가/저가: {stck_oprc} / {stck_hgpr} / {stck_lwpr}\n"
        f"  거래량: {acml_vol}"
    )


def format_portfolio_item(code: str, price_data: dict, qty: int) -> str:
    prpr = price_data.get("stck_prpr", "0")
    try:
        price = int(prpr)
    except ValueError:
        price = 0
    subtotal = price * qty
    name = price_data.get("prdt_name", code)
    return (
        f"[{code}] {name}\n"
        f"  현재가: {price:>10,} 원  x {qty:>4}주  =  {subtotal:>12,} 원"
    )


def format_portfolio_total(items: list[tuple[str, dict, int]]) -> str:
    lines: list[str] = []
    grand_total = 0
    for code, price_data, qty in items:
        prpr = price_data.get("stck_prpr", "0")
        try:
            price = int(prpr)
        except ValueError:
            price = 0
        subtotal = price * qty
        grand_total += subtotal
        lines.append(format_portfolio_item(code, price_data, qty))
    lines.append("─" * 50)
    lines.append(f"{'총 평가금액':>38}  {grand_total:>12,} 원")
    return "\n\n".join(lines)


def _is_likely_overseas(code: str) -> bool:
    return not (len(code) == 6 and code.isdigit())


def fetch_usd_krw_rate() -> float | None:
    """공개 환율 API 로 USD→KRW 환율을 조회한다."""
    try:
        resp = requests.get(
            "https://open.er-api.com/v6/latest/USD",
            timeout=10,
        )
        resp.raise_for_status()
        rates = resp.json().get("rates", {})
        krw = rates.get("KRW")
        if krw:
            return float(krw)
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(
        description="한국투자증권 KIS Open API — 국내/해외 주식 현재가 조회",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "인증 정보 우선순위:\n"
            "  1. ~/.config/kis/env 파일 (KEY=VALUE 형식)\n"
            "  2. KIS_APP_KEY / KIS_APP_SECRET 환경변수\n\n"
            "예시:\n"
            "  python kis_stock_api.py 005930                     # 국내 단일\n"
            "  python kis_stock_api.py 005930 000660              # 국내 여러 종목\n"
            "  python kis_stock_api.py KMI                        # 해외 단일 (자동감지)\n"
            "  python kis_stock_api.py AAPL MSFT TSLA             # 해외 여러 종목\n"
            "  python kis_stock_api.py --build-index              # 국내 종목 인덱스 생성\n"
            "  python kis_stock_api.py --build-overseas-index     # 해외 종목 인덱스 생성\n"
            "  python kis_stock_api.py \"Kinder Morgan\"           # 회사명 검색 (6자리X → overseas)\n"
            "  python kis_stock_api.py -f portfolio.csv           # 국내 포트폴리오\n"
            "  python kis_stock_api.py -f portfolio.csv --overseas # 해외 포트폴리오\n"
        ),
    )
    parser.add_argument(
        "codes",
        nargs="*",
        metavar="종목코드/명",
        help="종목코드 또는 회사명 (6자리숫자=국내, 그외=해외 자동감지)",
    )
    parser.add_argument(
        "-f", "--file",
        type=str,
        metavar="CSV",
        help="포트폴리오 CSV 파일 (code,qty 또는 name,qty 형식)",
    )
    parser.add_argument(
        "--build-index",
        action="store_true",
        help="국내 종목명→코드 변환 인덱스 생성",
    )
    parser.add_argument(
        "--build-overseas-index",
        action="store_true",
        help="해외(US) 종목명→티커 변환 인덱스 생성",
    )
    parser.add_argument(
        "--overseas",
        action="store_true",
        help="해외주식 모드 강제 (파일/종목명 입력시)",
    )
    parser.add_argument(
        "--mixed",
        action="store_true",
        help="국내+해외 혼합 포트폴리오 모드 (CSV 각 행을 국내 먼저 시도 → 해외 fallback)",
    )
    parser.add_argument(
        "--rate",
        type=float,
        metavar="환율",
        help="USD→KRW 환율 직접 지정 (미지정시 자동조회)",
    )
    args = parser.parse_args()

    # ── 인덱스 빌드 모드 ────────────────────────────────────────────
    if args.build_index:
        _build_stock_code_map()
        print("국내 종목 인덱스 생성 완료.")
        return

    if args.build_overseas_index:
        _build_overseas_stock_map()
        print("해외(US) 종목 인덱스 생성 완료.")
        return

    if not args.file and not args.codes:
        parser.error("종목코드 또는 --file CSV 파일을 입력해주세요.")
    if args.file and args.codes:
        parser.error("종목코드와 --file 은 동시에 사용할 수 없습니다.")

    try:
        _get_credential("KIS_APP_KEY")
        _get_credential("KIS_APP_SECRET")
    except RuntimeError as e:
        parser.error(str(e))

    client = KISClient()

    # ── 포트폴리오 모드 ──────────────────────────────────────────────
    if args.file:
        if args.overseas:
            ovs_map = _build_overseas_stock_map()
            # 해외 포트폴리오: CSV 직접 파싱 (load_portfolio의 국내용 resolve 호환 안됨)
            items: list[PortfolioItem] = []
            with open(args.file, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    qty_raw = row.get("qty", "").strip()
                    if not qty_raw:
                        continue
                    qty = float(qty_raw)
                    code = row.get("code", "").strip()
                    name = row.get("name", "").strip()
                    if code:
                        ticker, exch, _ = resolve_overseas_stock_ticker(code, ovs_map)
                        items.append(PortfolioItem(code=ticker, qty=qty, name=name or ticker))
                    elif name:
                        ticker, exch, _ = resolve_overseas_stock_ticker(name, ovs_map)
                        items.append(PortfolioItem(code=ticker, qty=qty, name=name))
            if not items:
                print("CSV에 유효한 종목이 없습니다.")
                return
            for i, item in enumerate(items):
                if i > 0:
                    time.sleep(1.5)
                try:
                    entry = ovs_map.get(item.code, {})
                    exch = entry.get("exchange", "NYS")
                    data = client.overseas_inquire_price(exch, item.code)
                    last = data.get("last", "-")
                    try:
                        val = float(last) * item.qty
                        val_str = f"{val:>12,.2f}"
                    except (ValueError, TypeError):
                        val_str = "-"
                    print(f"\n[{item.code}] {item.name}")
                    print(format_overseas_price(item.code, exch, data))
                    print(f"  평가금액: {val_str} USD")
                except Exception as e:
                    print(f"\n[{item.code}] {item.name} — ERROR: {e}")
            return

        if args.mixed:
            code_map = _build_stock_code_map()
            ovs_map = _build_overseas_stock_map()

            pending_domestic: list[tuple[str, float, str]] = []
            pending_overseas: list[tuple[str, str, float, str]] = []

            with open(args.file, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    qty_raw = row.get("qty", "").strip()
                    if not qty_raw:
                        continue
                    qty = float(qty_raw)
                    code = row.get("code", "").strip()
                    name = row.get("name", "").strip()
                    input_val = code or name
                    if not input_val:
                        continue

                    if code and len(code) == 6 and code.isdigit():
                        pending_domestic.append((code, qty, name or code))
                        continue

                    if name and re.search(r'[\uac00-\ud7a3]', name):
                        ovs_ticker = KOREAN_OVS_MAP.get(name.strip())
                        if ovs_ticker:
                            entry = ovs_map.get(ovs_ticker, {})
                            exch = entry.get("exchange", "NYS")
                            print(f"  (해외) {name} → {ovs_ticker} ({exch})")
                            pending_overseas.append((ovs_ticker, exch, qty, name))
                            continue
                        resolved = resolve_stock_name(name, code_map)
                        print(f"  (국내) {name} → {resolved}")
                        pending_domestic.append((resolved, qty, name))
                        continue

                    try:
                        ticker, exch, _ = resolve_overseas_stock_ticker(input_val, ovs_map)
                        print(f"  (해외) {input_val} → {ticker} ({exch})")
                        pending_overseas.append((ticker, exch, qty, name or ticker))
                        continue
                    except Exception:
                        pass

                    if name:
                        resolved = resolve_stock_name(name, code_map)
                        print(f"  (국내) {name} → {resolved}")
                        pending_domestic.append((resolved, qty, name))
                        continue

                    print(f"\n[{input_val}] ERROR — 종목을 찾을 수 없습니다.")

            domestic_results: dict[str, tuple[dict, float, str]] = {}
            overseas_results: list[tuple[str, str, dict, float, str]] = []

            if pending_domestic:
                codes = [c for c, _, _ in pending_domestic]
                try:
                    batch_data = client.inquire_prices_batch(*codes)
                except Exception as e:
                    print(f"[BATCH] 국내 멀티종목 조회 실패 — {e}")
                    batch_data = {}
                for code, qty, name in pending_domestic:
                    data = batch_data.get(code)
                    if data:
                        domestic_results[code] = (data, qty, name)
                    else:
                        print(f"[{code}] 조회 결과 없음 (개별 조회 시도)")
                        try:
                            data = client.inquire_price(code)
                            domestic_results[code] = (data, qty, name)
                            time.sleep(0.3)
                        except Exception as e:
                            print(f"\n[{code}] ERROR — {e}")

            if pending_overseas:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                    futures = [ex.submit(client.overseas_inquire_price, exch, ticker)
                               for ticker, exch, _, _ in pending_overseas]
                    for f, (ticker, exch, qty, name) in zip(futures, pending_overseas):
                        try:
                            data = f.result()
                            overseas_results.append((ticker, exch, data, qty, name))
                        except Exception as e:
                            err = str(e)
                            if "EGW00201" in err:
                                time.sleep(2.0)
                                try:
                                    data = client.overseas_inquire_price(exch, ticker)
                                    overseas_results.append((ticker, exch, data, qty, name))
                                    continue
                                except Exception as e2:
                                    err = str(e2)
                            print(f"[{ticker}] ERROR — {err}")

            if domestic_results:
                print("\n" + "=" * 55)
                print("  📈 국내주식 포트폴리오")
                print("=" * 55)
                dom_total = 0
                for code in (c for c, _, _ in pending_domestic):
                    entry = domestic_results.get(code)
                    if not entry:
                        continue
                    data, qty, name = entry
                    prpr = data.get("stck_prpr", "0")
                    try:
                        price = int(prpr)
                    except ValueError:
                        price = 0
                    subtotal = price * qty
                    dom_total += subtotal
                    name_label = data.get("prdt_name", code)
                    print(f"[{code}] {name_label}")
                    print(f"  현재가: {price:>10,} 원  x {qty:>4}주  =  {subtotal:>12,} 원")
                    print()
                print("─" * 55)
                print(f"{'국내 총 평가금액':>38}  {dom_total:>12,} 원")

            if overseas_results:
                print("\n" + "=" * 55)
                print("  🌍 해외주식 포트폴리오")
                print("=" * 55)
                ovs_total = 0.0
                for ticker, exch, data, qty, name in overseas_results:
                    last = data.get("last", "-")
                    print(format_overseas_price(ticker, exch, data))
                    try:
                        val = float(last) * qty
                        ovs_total += val
                        print(f"  평가금액: {val:>12,.2f} USD")
                    except (ValueError, TypeError):
                        print(f"  평가금액: -")
                    print()
                print("─" * 55)
                print(f"{'해외 총 평가금액':>38}  {ovs_total:>12,.2f} USD")

            if domestic_results or overseas_results:
                if overseas_results:
                    rate = args.rate or fetch_usd_krw_rate()
                    if rate:
                        grand_total = dom_total + (ovs_total * rate)
                        print("\n" + "=" * 55)
                        print(f"  📊 포트폴리오 최종 합계")
                        print("=" * 55)
                        print(f"{'국내':>32}  {dom_total:>12,} 원")
                        print(f"{'해외 (USD → KRW)':>32}  {ovs_total * rate:>12,.0f} 원  (환율 {rate:,.0f}원)")
                        print("─" * 55)
                        print(f"{'최종 합계':>32}  {grand_total:>12,.0f} 원")
                    else:
                        print(f"\n⚠️  USD→KRW 환율을 조회할 수 없습니다. --rate 로 직접 지정해주세요.")
            return

        else:
            code_map = _build_stock_code_map()
            portfolio = load_portfolio(args.file, code_map)
            codes = [item.code for item in portfolio]
            try:
                batch = client.inquire_prices_batch(*codes)
            except Exception as e:
                print(f"[BATCH] 멀티종목 조회 실패 — {e}")
                return
            results: list[tuple[str, dict, int]] = []
            for item in portfolio:
                data = batch.get(item.code)
                if data:
                    results.append((item.code, data, item.qty))
                else:
                    label = item.name or item.code
                    print(f"[{label}] 조회 결과 없음")
            if results:
                print("\n" + format_portfolio_total(results))
            return

    # ── 종목 직접 입력 모드 ──────────────────────────────────────────
    overseas_mode = args.overseas or _is_likely_overseas(args.codes[0])

    if overseas_mode:
        ovs_map: dict[str, dict] | None = None
        try:
            ovs_map = _build_overseas_stock_map()
        except RuntimeError:
            pass  # 인덱스 없어도 티커 직접입력은 동작

    for i, code_or_name in enumerate(args.codes):
        if i > 0:
            time.sleep(1.2 if not overseas_mode else 1.2)

        if not overseas_mode:
            try:
                data = client.inquire_price(code_or_name)
                print(f"\n[{code_or_name}]")
                print(format_price(data))
            except Exception as e:
                print(f"\n[{code_or_name}] ERROR — {e}")
        else:
            try:
                ticker, exch, prdt_type = resolve_overseas_stock_ticker(code_or_name, ovs_map)
                # 먼저 상품기본정보로 기업정보 확인
                try:
                    info = client.overseas_search_info(prdt_type, ticker)
                    print(f"\n[{ticker}]")
                    print(format_overseas_search_info(ticker, info))
                except Exception:
                    print(f"\n[{ticker}] (상품정보 조회 실패)")
                time.sleep(0.6)  # API rate limit 방지
                # 현재가 조회
                price = client.overseas_inquire_price(exch, ticker)
                print(format_overseas_price(ticker, exch, price))
            except Exception as e:
                print(f"\n[{code_or_name}] ERROR — {e}")


if __name__ == "__main__":
    main()
