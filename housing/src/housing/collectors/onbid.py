"""온비드 부동산 공매 물건 수집기 — 대지(주택건축가능) 전용.

연동 API:
- B010003/OnbidRlstListSrvc2/getRlstCltrList2: 차세대 온비드 부동산 물건목록 조회

주요 필터:
- prptDivCd=0007,0010,0005,0002 (압류+국유+기타일반+공유)
- cltrUsgSclsCtgrId=10101 (대지) — 주택 건축 가능 토지
- dspsMthodCd=0001 (매각)
- bidDivCd=0001 (인터넷 입찰)
- lctnSdnm: 서울특별시, 경기도 (지역별 반복 수집)

운영: 한국자산관리공사(KAMCO)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.housing.collectors.base import BaseCollector
from src.housing.models import SaleListing, SupplyType, SaleStatus

logger = logging.getLogger(__name__)

# 차세대 온비드 부동산 물건목록 조회 API
ONBID_API_URL = (
    "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2/getRlstCltrList2"
)

# 수집 대상 재산유형 (압류+국유+기타일반+공유, 콤마로 다중 전달)
# 대지(10101) 기준: 압류 4,115 / 기타일반 465 / 국유 169 / 공유 101 = 총 4,850건
PRPT_DIV_CD = "0007,0010,0005,0002"

# 입찰상태 → SaleStatus 매핑
PBCT_STAT_MAP: dict[str, SaleStatus] = {
    "입찰준비중": SaleStatus.PLANNED,
    "입찰중": SaleStatus.OPEN,
    "입찰예정": SaleStatus.PLANNED,
    "입찰종료": SaleStatus.CLOSED,
    "유찰": SaleStatus.UNSOLD,
    "입찰취소": SaleStatus.CLOSED,
}

# 용도 코드: 토지(10100) / 대지(10101)
CLTR_USG_MCLS_CTGR_ID = "10100"
CLTR_USG_SCLS_CTGR_ID = "10101"


class OnbidCollector(BaseCollector):
    """온비드 부동산 공매 — 대지 물건 수집기.

    압류/국유/기타일반/공유 재산 중 대지(주택건축가능) 매각 물건을 수집합니다.
    """

    PAGE_SIZE = 500
    MAX_PAGES = 2

    def __init__(self, config: Optional[Any] = None):
        super().__init__(config)
        self.source_name = "onbid"

    REGIONS = ["서울특별시", "경기도"]

    def collect(self, **kwargs) -> list[SaleListing]:
        mock = kwargs.get("mock", False)
        if mock:
            results = self._mock_collect()
        elif not self.client._service_key or self.client._service_key.startswith("${"):
            logger.warning("DATA_GO_KR_API_KEY not configured. Falling back to mock data.")
            results = self._mock_collect()
        else:
            results = []
            logger.info("Onbid — collecting 대지 (서울/경기도)...")
            try:
                for region in self.REGIONS:
                    items = self._fetch_items(region)
                    for item in items:
                        listing = self._to_listing(item)
                        if listing:
                            results.append(listing)
                    logger.info("  → %s: %d items", region, len(items))
                logger.info("  → total %d 대지 items", len(results))
            except Exception as e:
                logger.error("Onbid fetch failed: %s", e)

        before = len(results)
        results = [r for r in results if r.status in (SaleStatus.PLANNED, SaleStatus.OPEN)]
        filtered = before - len(results)
        if filtered:
            logger.info("  → excluded %d non-biddable items", filtered)
        return results

    def _fetch_items(self, region: str) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "pageNo": 1,
            "numOfRows": self.PAGE_SIZE,
            "resultType": "json",
            "prptDivCd": PRPT_DIV_CD,
            "pvctTrgtYn": "N",
            "cltrUsgMclsCtgrId": CLTR_USG_MCLS_CTGR_ID,
            "cltrUsgSclsCtgrId": CLTR_USG_SCLS_CTGR_ID,
            "dspsMthodCd": "0001",
            "bidDivCd": "0001",
            "lctnSdnm": region,
        }

        all_items: list[dict[str, Any]] = []
        for page in range(1, self.MAX_PAGES + 1):
            params["pageNo"] = page
            try:
                resp = self.client.fetch(ONBID_API_URL, dict(params))
            except Exception as exc:
                logger.warning("Onbid %s page %d failed: %s", region, page, exc)
                break

            header = resp.get("header", {})
            if header.get("resultCode") != "00":
                logger.warning(
                    "Onbid %s page %d: code=%s msg=%s",
                    region, page, header.get("resultCode"), header.get("resultMsg"),
                )
                break

            body = resp.get("body", {})
            items = body.get("items", {}).get("item", [])
            if not items:
                break

            all_items.extend(items)

            total_count = body.get("totalCount", 0)
            total_pages = (total_count + self.PAGE_SIZE - 1) // self.PAGE_SIZE
            if page >= total_pages:
                break

        return all_items

    def _to_listing(self, item: dict[str, Any]) -> Optional[SaleListing]:
        """API 응답 아이템을 SaleListing으로 변환.

        온비드 부동산 목록 API 응답 필드:
        - onbidCltrNm: 물건명 (주소 포함)
        - lctnSdnm / lctnSggnm / lctnEmdNm: 시도/시군구/읍면동
        - cltrUsgMclsCtgrNm: 용도중분류명 (토지/주거용건물/...)
        - cltrUsgSclsCtgrNm: 용도소분류명 (대지/임야/잡종지/전/답/...)
        - pbctStatCd / pbctStatNm: 입찰상태코드/명
        - landSqms: 토지면적(㎡)
        - lowstBidPrcIndctCont: 최저입찰가 (문자열, 원)
        - apslEvlAmt: 감정평가액 (숫자, 원)
        - orgNm: 공고기관명
        - cltrBidBgngDt: 입찰시작일시 (YYYYMMDDHHMM)
        - cltrBidEndDt: 입찰종료일시
        - pbctNo / pbctNsq: 공고번호/차수
        - thnlImgUrlAdr: 썸네일 이미지 URL
        - ltnoPnu: 지번 PNU
        - rdnmPnu: 도로명 PNU
        - usbdNft: 유찰횟수
        - totamtAr: 총면적(㎡) (landSqms와 동일)
        - dsmnAmt: 낙찰예정금액(최저입찰가, 숫자, 원)
        """
        try:
            name = item.get("onbidCltrNm", "").strip()
            if not name:
                return None

            # 지역
            parts = [
                item.get("lctnSdnm", ""),
                item.get("lctnSggnm", ""),
                item.get("lctnEmdNm", ""),
            ]
            region = " ".join(p for p in parts if p)

            # 상태
            pbct_stat_nm = item.get("pbctStatNm", "")
            status = PBCT_STAT_MAP.get(pbct_stat_nm, SaleStatus.PLANNED)

            # 면적 (㎡)
            raw_land = item.get("landSqms", 0)
            try:
                land_sqms = int(float(str(raw_land))) if raw_land else 0
            except (ValueError, TypeError):
                land_sqms = 0

            # 최저입찰가 (원 → 만원)
            raw_price = item.get("lowstBidPrcIndctCont", "0")
            if isinstance(raw_price, str):
                raw_price = raw_price.replace(",", "").strip()
            try:
                price_won = int(float(str(raw_price)))
            except (ValueError, TypeError):
                price_won = 0
            # 원 → 만원
            price_man = price_won // 10000 if price_won > 0 else 0

            # 감정평가액 (원)
            raw_appraisal = item.get("apslEvlAmt", 0)
            try:
                appraisal_won = int(float(str(raw_appraisal)))
            except (ValueError, TypeError):
                appraisal_won = 0

            # 용도
            supply_purpose = item.get("cltrUsgSclsCtgrNm", "")

            # 입찰시작일 → 공고일
            bid_start = item.get("cltrBidBgngDt", "")
            announce_date = bid_start[:8] if len(bid_start) >= 8 else ""
            if announce_date:
                announce_date = (
                    announce_date[:4] + "-" + announce_date[4:6] + "-" + announce_date[6:8]
                )

            # 상세 URL (온비드 물건 상세 페이지)
            onbid_cltrno = item.get("onbidCltrno", "")
            onbid_pbanc_no = item.get("onbidPbancNo", "")
            pbct_cdtn_no = item.get("pbctCdtnNo", "")
            pbct_no = item.get("pbctNo", "")
            dtl_url = ""
            if onbid_cltrno and onbid_pbanc_no and pbct_cdtn_no and pbct_no:
                dtl_url = (
                    f"https://www.onbid.co.kr/op/cltrpbancinf/cltrdtl/CltrDtlController/mvmnCltrDtl.do"
                    f"?cltrPrptDivCd=5&cltrScrnGrpCd=0"
                    f"&onbidCltrno={onbid_cltrno}&onbidPbancNo={onbid_pbanc_no}"
                    f"&pbctCdtnNo={pbct_cdtn_no}&pbctNo={pbct_no}"
                )

            # 이미지 URL
            image_url = item.get("thnlImgUrlAdr", "")

            # PNU
            pnu = item.get("ltnoPnu", "") or item.get("rdnmPnu", "")

            # 유찰횟수
            raw_nft = item.get("usbdNft", 0)
            try:
                usbd_nft = int(float(str(raw_nft)))
            except (ValueError, TypeError):
                usbd_nft = 0

            # 총면적 (㎡) — landSqms 대체 가능
            raw_totamt = item.get("totamtAr", land_sqms)
            try:
                totamt_ar = int(float(str(raw_totamt)))
            except (ValueError, TypeError):
                totamt_ar = land_sqms

            # 낙찰예정금액 (원, 숫자형) — lowstBidPrcIndctCont와 동일 값
            raw_dsmn = item.get("dsmnAmt", 0)
            try:
                dsmn_amt = int(float(str(raw_dsmn)))
            except (ValueError, TypeError):
                dsmn_amt = price_won

            return SaleListing(
                name=name,
                region=region,
                supply_type=SupplyType.LAND,
                status=status,
                units=land_sqms,
                price=price_man,
                builder=item.get("orgNm", "한국자산관리공사"),
                supply_purpose=supply_purpose,
                announcement_date=announce_date,
                raw_data={
                    "dtl_url": dtl_url,
                    "image_url": image_url,
                    "pnu": pnu,
                    "appraisal_value": appraisal_won,
                    "usbd_nft": usbd_nft,
                    "totamt_ar": totamt_ar,
                    "dsmn_amt": dsmn_amt,
                    "bid_start_date": item.get("cltrBidBgngDt", ""),
                    "bid_end_date": item.get("cltrBidEndDt", ""),
                    "prpt_div_nm": item.get("prptDivNm", ""),
                    "rqst_org_nm": item.get("rqstOrgNm", ""),
                },
                source="onbid",
            )
        except Exception as exc:
            logger.warning("Onbid _to_listing failed for item: %s", exc)
            return None

    def _mock_collect(self) -> list[SaleListing]:
        mock_data = [
            {
                "onbidCltrNm": "서울특별시 송파구 석촌동 242-15 대지",
                "lctnSdnm": "서울특별시",
                "lctnSggnm": "송파구",
                "lctnEmdNm": "석촌동",
                "ltnoPnu": "1171010500102420015",
                "cltrUsgSclsCtgrNm": "대지",
                "pbctStatNm": "입찰준비중",
                "landSqms": 330,
                "totamtAr": 330,
                "lowstBidPrcIndctCont": "850000000",
                "dsmnAmt": 850000000,
                "apslEvlAmt": 1200000000,
                "usbdNft": 0,
                "cltrBidBgngDt": "202608011400",
                "cltrBidEndDt": "202608031700",
                "pbctNo": "10075000",
                "pbctNsq": "001",
                "orgNm": "한국자산관리공사",
            },
            {
                "onbidCltrNm": "경기도 성남시 분당구 정자동 212-1 대지",
                "lctnSdnm": "경기도",
                "lctnSggnm": "성남시 분당구",
                "lctnEmdNm": "정자동",
                "ltnoPnu": "4113510300102120001",
                "cltrUsgSclsCtgrNm": "대지",
                "pbctStatNm": "입찰중",
                "landSqms": 528,
                "totamtAr": 528,
                "lowstBidPrcIndctCont": "2100000000",
                "dsmnAmt": 2100000000,
                "apslEvlAmt": 2800000000,
                "usbdNft": 1,
                "cltrBidBgngDt": "202607151400",
                "cltrBidEndDt": "202607171700",
                "pbctNo": "10075001",
                "pbctNsq": "001",
                "orgNm": "한국자산관리공사",
            },
            {
                "onbidCltrNm": "서울특별시 강남구 역삼동 670-10 대지",
                "lctnSdnm": "서울특별시",
                "lctnSggnm": "강남구",
                "lctnEmdNm": "역삼동",
                "ltnoPnu": "1168010500167000100",
                "cltrUsgSclsCtgrNm": "대지",
                "pbctStatNm": "유찰",
                "landSqms": 198,
                "totamtAr": 198,
                "lowstBidPrcIndctCont": "1500000000",
                "dsmnAmt": 1500000000,
                "apslEvlAmt": 2400000000,
                "usbdNft": 2,
                "cltrBidBgngDt": "202607011400",
                "cltrBidEndDt": "202607031700",
                "pbctNo": "10075002",
                "pbctNsq": "002",
                "orgNm": "한국자산관리공사",
            },
        ]
        results = []
        for data in mock_data:
            listing = self._to_listing(data)
            if listing:
                results.append(listing)
        return results
