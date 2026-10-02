#!/usr/bin/env python3
"""支持 python src/main.py 和 python -m src.main。"""
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app import main

if __name__ == "__main__":
    raise SystemExit(main())
