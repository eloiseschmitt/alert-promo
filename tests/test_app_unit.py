"""Unit tests for core helpers in app.py."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, List

import pytest
import requests

from constants import KEYWORDS
from models import ScanResult
from app import (
    check_url,
    find_keywords,
    normalize_text,
    read_urls,
    scan_urls,
    to_csv_bytes,
)


class _DummyResponse:
    def __init__(self, *, status_code: int, url: str, text: str) -> None:
        self.status_code = status_code
        self.url = url
        self.text = text


class _DummySession:
    def __init__(self, responses: Iterable[_DummyResponse], *, raise_exc: Exception | None = None) -> None:
        self._responses = iter(responses)
        self._exc = raise_exc
        self.get_calls: List[str] = []
        self.closed = False

    def get(self, url: str, timeout: int, allow_redirects: bool) -> _DummyResponse:  # pragma: no cover - signature mirrors requests
        if self._exc is not None:
            raise self._exc
        self.get_calls.append(url)
        return next(self._responses)

    def close(self) -> None:
        self.closed = True


def test_find_keywords_detects_words_and_percentage() -> None:
    text = normalize_text("Mega Réduction -60% sur tout !")
    found = find_keywords(text, KEYWORDS)
    assert "réduction" in found
    assert "-60%" in found


def test_read_urls_filters_comments_and_blanks(tmp_path: Path) -> None:
    content = """
    # comment
    https://example.com

    https://promo.test
    """
    file_path = tmp_path / "urls.txt"
    file_path.write_text(content, encoding="utf-8")

    urls = read_urls(file_path)

    assert urls == ["https://example.com", "https://promo.test"]


def test_check_url_success_detects_promo() -> None:
    html = "<html><body>Grande promo! -50% sur tout.</body></html>"
    session = _DummySession([
        _DummyResponse(status_code=200, url="https://example.com/final", text=html),
    ])

    result = check_url(session, "https://example.com")

    assert result["status"] == "ok"
    assert result["http_status"] == 200
    assert result["final_url"] == "https://example.com/final"
    assert result["has_promo"] is True
    assert "promo" in result["found"]


def test_check_url_handles_http_error() -> None:
    session = _DummySession([
        _DummyResponse(status_code=503, url="https://example.com/final", text="maintenance"),
    ])

    result = check_url(session, "https://example.com")

    assert result["status"] == "http_503"
    assert result["has_promo"] is False


def test_check_url_handles_timeout() -> None:
    session = _DummySession([], raise_exc=requests.exceptions.Timeout("timeout"))

    result = check_url(session, "https://example.com")

    assert result["status"] == "timeout"
    assert "timeout" in (result["error"] or "")


def test_to_csv_bytes_serialises_found_entries() -> None:
    rows: List[ScanResult] = [
        {
            "url": "https://example.com",
            "status": "ok",
            "http_status": 200,
            "final_url": "https://example.com/final",
            "has_promo": True,
            "found": ["promo", "-50%"],
            "error": None,
        }
    ]

    csv_bytes = to_csv_bytes(rows)
    decoded = csv_bytes.decode("utf-8")

    reader = csv.DictReader(decoded.splitlines())
    row = next(reader)
    assert row["found"] == "promo, -50%"
    assert row["has_promo"] == "True"


def test_scan_urls_uses_custom_session(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _DummyResponse(status_code=200, url="https://a.example/final", text="Promo -50%"),
        _DummyResponse(status_code=404, url="https://b.example/final", text="not found"),
    ]

    dummy_session = _DummySession(responses)

    def _fake_build_session() -> _DummySession:
        return dummy_session

    monkeypatch.setattr("scanner.build_session", _fake_build_session)

    results = scan_urls(["https://a.example", "https://b.example"], timeout=5)

    assert len(results) == 2
    assert dummy_session.get_calls == ["https://a.example", "https://b.example"]
    assert dummy_session.closed is True
