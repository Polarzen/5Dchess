"""Run the Web host for Cloudflare-exposed P2P play without Flask debug mode."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.web import run_server


if __name__ == "__main__":
    run_server(host="127.0.0.1", port=5000, debug=False)
