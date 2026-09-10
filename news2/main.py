#!/usr/bin/env python3
"""news2 — Tavily 기반 뉴스 수집기.

Usage:
    python main.py --mode search
    python main.py --mode research
    python main.py --mode search --regions asia europe
    python main.py --mode research --query "AI news today"
"""

from src.news.cli import main

if __name__ == "__main__":
    main()
