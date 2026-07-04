#!/usr/bin/env python3
"""여행 코스 자동 생성기 — TourAPI 기반 지역 관광정보 리포트.

Usage:
    python main.py --region 서울 --date 2026-07-11
    python main.py --region 부산 --date 2026-08-15 --emails user@example.com
    python main.py --region 제주 --date 2026-07-30 --no-cache --output my-report.html
"""
from __future__ import annotations

import sys

from src.tour.cli import main

if __name__ == "__main__":
    sys.exit(main())
