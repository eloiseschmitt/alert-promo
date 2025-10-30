"""Shared configuration constants for the application."""

from __future__ import annotations

from pathlib import Path
import re
from typing import List

from models import ScanResult, UrlEntry

DEFAULT_TIMEOUT = 10
URLS_FILE = Path("websites.txt")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

KEYWORDS: List[str] = [
    "promo",
    "promos",
    "promotion",
    "promotions",
    "soldes",
    "remise",
    "réduction",
    "reductions",
    "sale",
    "sales",
    "discount",
    "discounts",
    "deal",
    "deals",
    "clearance",
    "markdown",
    "promotion",
    "promotions",
    "offers",
]

PERCENT_REGEX = re.compile(
    r"-?\s?(?:50|60|70)\s?%",
    flags=re.IGNORECASE,
)
LAST_RESULTS: List[ScanResult] = []
LAST_URL_ENTRIES: List[UrlEntry] = []
RESULT_HISTORY_FILE = Path("data/last_results.json")

_EXPORTED_NAMES = (
    "DEFAULT_TIMEOUT",
    "URLS_FILE",
    "USER_AGENT",
    "KEYWORDS",
    "PERCENT_REGEX",
    "LAST_RESULTS",
    "LAST_URL_ENTRIES",
    "RESULT_HISTORY_FILE",
)

__all__ = [name for name in _EXPORTED_NAMES if name in globals()]
