"""config.yaml 로더 — 경로는 전부 dualdb 루트 상대."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent          # .../dualdb
REPO_ROOT = ROOT.parent                                 # .../ai-investing (export 연동용)

_cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

ANCHORS = _cfg["anchors"]
DB_PATH = ROOT / _cfg["paths"]["db"]
RAW_DIR = ROOT / _cfg["paths"]["raw"]
SEEDS_DIR = ROOT / _cfg["paths"]["seeds"]
REPORTS_DIR = ROOT / _cfg["paths"]["reports"]

FRED_DAILY = _cfg["fred"]["daily"]
FRED_MONTHLY = _cfg["fred"]["monthly"]
STOOQ = _cfg["stooq"]
YAHOO_INDICES = _cfg["yahoo_indices"]
YAHOO_DAILY = _cfg["yahoo_daily"]
RITTER_PAGE = _cfg["ritter"]["page"]
SHILLER_URL = _cfg["shiller"]["url"]

REQ_DELAY = float(_cfg["request"]["delay_sec"])
REQ_RETRIES = int(_cfg["request"]["retries"])
REQ_TIMEOUT = int(_cfg["request"]["timeout"])
