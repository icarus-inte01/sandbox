#!/usr/bin/env python3
"""분양정보 유망도 추천 시스템 - 진입점.

Usage:
    python main.py --help
    python main.py collect --mock
    python main.py collect --source cheongyak --mock
    python main.py analyze --output table --mock
    python main.py report --mock
    python main.py all --mock
"""
from __future__ import annotations

import sys

from src.housing.cli import main

if __name__ == "__main__":
    sys.exit(main())
