"""Core scanning utilities for promotion detection."""

from __future__ import annotations

import csv
import io
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, cast

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from constants import DEFAULT_TIMEOUT, KEYWORDS, PERCENT_REGEX, URLS_FILE, USER_AGENT
from models import ScanResult

__all__ = [
    "build_session",
    "normalize_text",
    "extract_visible_text",
    "find_keywords",
    "read_urls",
    "check_url",
    "to_csv_bytes",
    "scan_urls",
    "run_batch_scan",
]


def build_session() -> requests.Session:
    """Create a configured `requests.Session` with retries and headers."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "fr,fr-FR;q=0.9,en;q=0.8",
    })
    return session


def normalize_text(text: str) -> str:
    """Lowercase input text and append an ASCII-folded variant."""
    lowered = text.lower()
    ascii_folded = (
        unicodedata.normalize("NFKD", lowered)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return lowered + "\n" + ascii_folded


def extract_visible_text(html: str) -> str:
    """Strip non-visual tags from HTML and return normalized text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return normalize_text(text)


def find_keywords(text: str, keywords: List[str]) -> List[str]:
    """Return unique keywords (and percentage hits) detected in text."""
    found: List[str] = []
    for kw in keywords:
        if kw.lower() in text:
            found.append(kw)
    percents = PERCENT_REGEX.findall(text)
    if percents:
        found.extend(sorted(set(p.strip() for p in percents)))
    return sorted(set(found), key=str.lower)


def read_urls(input_path: Path) -> List[str]:
    """Load URLs from a text file, skipping blanks and comments."""
    if not input_path.exists():
        return []
    lines = input_path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _make_empty_result(url: str) -> ScanResult:
    """Build an empty scan result for the provided URL."""
    return {
        "url": url,
        "status": None,
        "http_status": None,
        "final_url": None,
        "has_promo": False,
        "found": cast(List[str], []),
        "error": None,
    }


def check_url(session: requests.Session, url: str, timeout: int = DEFAULT_TIMEOUT) -> ScanResult:
    """Fetch an URL and report promotion-related findings."""
    original_url = url.strip()
    if not original_url:
        result = _make_empty_result(original_url)
        result["status"] = "skipped"
        return result

    request_url = original_url if original_url.startswith(("http://", "https://")) else f"https://{original_url}"
    result = _make_empty_result(original_url)

    try:
        resp = session.get(request_url, timeout=timeout, allow_redirects=True)
        result["http_status"] = resp.status_code
        result["final_url"] = str(resp.url)

        if resp.status_code != 200:
            result["status"] = f"http_{resp.status_code}"
            return result

        text = extract_visible_text(resp.text)
        found = find_keywords(text, KEYWORDS)
        result["found"] = found
        result["has_promo"] = bool(found)
        result["status"] = "ok"
        return result

    except requests.exceptions.SSLError as exc:
        result["status"] = "ssl_error"
        result["error"] = str(exc)
    except requests.exceptions.Timeout as exc:
        result["status"] = "timeout"
        result["error"] = str(exc)
    except requests.exceptions.RequestException as exc:
        result["status"] = "request_error"
        result["error"] = str(exc)

    return result


def to_csv_bytes(rows: Iterable[ScanResult]) -> bytes:
    """Serialize scan results into CSV and return the encoded bytes."""
    output = io.StringIO()
    fieldnames = ["url", "final_url", "http_status", "status", "has_promo", "found", "error"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        row: Dict[str, Any] = dict(r)
        row["found"] = ", ".join(r["found"]) if r["found"] else ""
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


def scan_urls(urls: Sequence[str], timeout: int = DEFAULT_TIMEOUT) -> List[ScanResult]:
    """Run `check_url` on every URL using a shared session."""
    if not urls:
        return []

    session = build_session()
    try:
        return [check_url(session, candidate, timeout=timeout) for candidate in urls]
    finally:
        session.close()


def run_batch_scan(timeout: int = DEFAULT_TIMEOUT) -> List[ScanResult]:
    """Read URLs from disk and return scan results."""
    urls = read_urls(URLS_FILE)
    return scan_urls(urls, timeout=timeout)
