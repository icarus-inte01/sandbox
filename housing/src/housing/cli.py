"""메인 CLI 인터페이스.

argparse 기반 명령행 인터페이스로 collect/analyze/report/all 서브커맨드를 제공합니다.
"""
from __future__ import annotations

import argparse
import logging
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any

from src.housing.config import Config
from src.housing.models import SaleListing, SupplyType

logger = logging.getLogger(__name__)

# Collector 팩토리 맵
COLLECTOR_MAP: dict[str, str] = {
    "cheongyak": "src.housing.collectors.cheongyak.CheongyakCollector",
    "lh": "src.housing.collectors.lh.LHCollector",
    "molit": "src.housing.collectors.molit.MolitTradeCollector",
    "naver": "src.housing.collectors.naver.NaverCollector",
}


def _import_collector(name: str):
    """동적 import 헬퍼."""
    import importlib
    module_path, class_name = COLLECTOR_MAP[name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def cmd_collect(args: argparse.Namespace) -> list[SaleListing]:
    """데이터 수집 서브커맨드."""
    all_listings: list[SaleListing] = []

    sources = ["cheongyak", "lh", "molit", "naver"] if args.source == "all" else [args.source]

    for src in sources:
        try:
            collector = _import_collector(src)
            logger.info("Collecting from %s...", src)

            if src == "lh":
                listings = collector.collect(mock=args.mock)
            elif src == "molit":
                # Molit collector는 실거래가 전용이므로 collect()는 empty 반환
                logger.info("Molit collector skipped (use analyze for price comparison)")
                continue
            else:
                listings = collector.collect(mock=args.mock)

            all_listings.extend(listings)
            logger.info("  -> %d items from %s", len(listings), src)
        except Exception as e:
            logger.error("Collector %s failed: %s", src, e)
            if not args.continue_on_error:
                raise

    return all_listings


def cmd_analyze(args: argparse.Namespace, listings: list[SaleListing]) -> list[SaleListing]:
    """유망도 분석 서브커맨드."""
    from src.housing.analyzer.scorer import calculate_scores_batch
    from src.housing.analyzer.ranker import rank_listings

    config = Config()
    scored = calculate_scores_batch(listings, config)
    ranked = rank_listings(scored)

    logger.info("Scored %d listings", len(ranked))

    if args.output == "table":
        print(f"\n{'순위':>4s} {'단지명':<24s} {'지역':<16s} {'점수':>6s}")
        print("-" * 54)
        for i, l in enumerate(ranked, 1):
            score = l.total_score or 0
            print(f"{i:4d} {l.name:<24s} {l.region:<16s} {score:6.1f}")

    return ranked


def cmd_report(args: argparse.Namespace, listings: list[SaleListing]) -> None:
    """리포트 생성 서브커맨드."""
    from src.housing.reporter.email_renderer import render_report

    html = render_report(listings, datetime.now().strftime("%Y-%m-%d"))

    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Report saved to %s (%d bytes)", output_path, len(html))
    print(f"Report saved: {output_path}")


def cmd_all(args: argparse.Namespace) -> None:
    """전체 파이프라인 실행 (collect → analyze → report)."""
    logger.info("=== E2E Pipeline Start ===")

    # Step 1: Collect
    listings = cmd_collect(args)
    logger.info("Total collected: %d listings", len(listings))

    if not listings:
        logger.warning("No listings collected. Skipping analysis & report.")
        return

    from src.housing.collectors.molit import MolitTradeCollector
    from src.housing.analyzer.price_comparator import estimate_market_price

    molit_collector = MolitTradeCollector()
    mock_mode = args.mock or not (molit_collector.client._service_key
                                   and not molit_collector.client._service_key.startswith("${"))

    # 청약홈 3-digit SUBSCRPT_AREA_CODE → 5-digit 법정동코드 (법정동 시/군/구)
    CHEONGYAK_CODE_TO_LAWD: dict[str, str] = {
        "100": "11110", "200": "42110", "300": "30110", "312": "44130",
        "338": "36110", "360": "43110", "400": "28110", "410": "41110",
        "500": "29110", "513": "46110", "560": "45110", "600": "26110",
        "621": "48120", "680": "31110", "690": "50110", "700": "27110",
        "712": "47110",
    }

    # 모든 시/도에 대해 실거래가 수집
    all_nearby_prices: dict[str, dict[str, Any]] = {}
    for cheongyak_code, lawd_cd in CHEONGYAK_CODE_TO_LAWD.items():
        prices = molit_collector.get_nearby_prices(lawd_cd, months_back=6, mock=mock_mode)
        all_nearby_prices[cheongyak_code] = prices
        if prices.get("trade_count", 0) > 0:
            logger.info("  -> nearby prices for %s: avg=%d만원 (%d건)",
                       cheongyak_code, prices["avg_price"], prices["trade_count"])

    if all_nearby_prices:
        logger.info("Collected nearby prices for %d regions", len(all_nearby_prices))

    for listing in listings:
        rc = listing.region_code
        if rc and rc in all_nearby_prices:
            nearby = all_nearby_prices[rc]
            if nearby.get("trade_count", 0) > 0:
                listing.market_price = int(nearby.get("avg_price", 0))
                rate, _ = estimate_market_price(listing, all_nearby_prices)
                if rate is not None:
                    listing.discount_rate = rate

    # Step 2: Analyze
    from src.housing.analyzer.scorer import calculate_scores_batch
    from src.housing.analyzer.ranker import rank_listings, top_n

    config = Config()
    scored = calculate_scores_batch(listings, config)
    ranked = rank_listings(scored)
    top = top_n(ranked, n=20)

    logger.info("Analyzed: %d listings, showing top %d", len(ranked), len(top))

    # Step 3: Report
    from src.housing.reporter.email_renderer import render_report
    report_date = datetime.now().strftime("%Y-%m-%d")
    html = render_report(top, report_date)

    output_path = args.output or "output/report.html"
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Report saved to %s (%d bytes)", output_path, len(html))
    logger.info("=== E2E Pipeline Complete ===")
    print(f"\nDone. Report: {output_path}")
    print(f"Total listings: {len(listings)}, Top {len(top)} scored & ranked.")

    if getattr(args, "send_email", False):
        _send_report_email(html, output_path)


def _send_report_email(html_content: str, report_path: str) -> None:
    """SMTP로 HTML 리포트를 이메일로 발송합니다.

    환경변수: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_TO, MAIL_FROM
    """
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    mail_to = os.environ.get("MAIL_TO", smtp_user)
    mail_from = os.environ.get("MAIL_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        logger.warning("SMTP_USER/SMTP_PASS not set. Skipping email.")
        return
    if not mail_to:
        logger.warning("MAIL_TO not set. Skipping email.")
        return

    msg = MIMEText(html_content, "html", "utf-8")
    msg["Subject"] = f"분양정보 유망도 리포트 ({datetime.now().strftime('%Y-%m-%d')})"
    msg["From"] = mail_from
    msg["To"] = mail_to

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(mail_from, [mail_to], msg.as_string())
        logger.info("Email sent to %s via %s:%d", mail_to, smtp_host, smtp_port)
        print(f"Email sent to {mail_to}")
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        print(f"Failed to send email: {e}")


def build_parser() -> argparse.ArgumentParser:
    """ArgumentParser를 생성합니다."""
    parser = argparse.ArgumentParser(
        prog="housing",
        description="분양정보 유망도 추천 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s collect --source cheongyak --mock
  %(prog)s analyze --output table
  %(prog)s report --output output/report.html
  %(prog)s all --mock
        """,
    )

    # 글로벌 옵션
    parser.add_argument("--mock", action="store_true", help="Mock 데이터 사용")
    parser.add_argument("--continue-on-error", action="store_true", default=True,
                        help="수집 오류 시 계속 진행 (기본: True)")
    parser.add_argument("-v", "--verbose", action="store_true", help="상세 로그 출력")

    subparsers = parser.add_subparsers(dest="command", help="명령어")

    # collect
    p_collect = subparsers.add_parser("collect", help="분양정보 수집")
    p_collect.add_argument(
        "--source", choices=list(COLLECTOR_MAP.keys()) + ["all"],
        default="all", help="수집 소스 (기본: all)"
    )

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="유망도 분석")
    p_analyze.add_argument(
        "--output", choices=["json", "table"], default="table",
        help="출력 형식 (기본: table)"
    )

    # report
    p_report = subparsers.add_parser("report", help="리포트 생성")
    p_report.add_argument("--output", default="output/report.html",
                          help="출력 파일 경로 (기본: output/report.html)")

    # all (E2E)
    p_all = subparsers.add_parser("all", help="전체 파이프라인 실행")
    p_all.add_argument("--output", default="output/report.html",
                       help="리포트 출력 경로 (기본: output/report.html)")
    p_all.add_argument("--source", choices=list(COLLECTOR_MAP.keys()) + ["all"],
                       default="all", help="수집 소스 (기본: all)")
    p_all.add_argument("--send-email", action="store_true",
                       help="리포트 생성 후 이메일 발송 (SMTP 환경변수 필요)")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # 로깅 설정
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not args.command:
        parser.print_help()
        return 0

    try:
        if args.command == "collect":
            cmd_collect(args)
        elif args.command == "analyze":
            # analyze는 이전 수집 데이터 필요 → 임시로 mock 수집 후 분석
            listings = cmd_collect(args)
            cmd_analyze(args, listings)
        elif args.command == "report":
            listings = cmd_collect(args)
            from src.housing.analyzer.scorer import calculate_scores_batch
            config = Config()
            scored = calculate_scores_batch(listings, config)
            cmd_report(args, scored)
        elif args.command == "all":
            cmd_all(args)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 1
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
