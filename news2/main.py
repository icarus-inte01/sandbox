#!/usr/bin/env python3
"""news2 — 국내 언론사 국제부 RSS 기반 뉴스 다이제스트.

Usage:
    python main.py
    python main.py --limit 10
    python main.py --output email --html-output news_digest.html
"""

from src.news.cli import main

if __name__ == "__main__":
    main()
