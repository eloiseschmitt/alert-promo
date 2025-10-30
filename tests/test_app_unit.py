"""Unit tests for core helpers in app.py."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable, List

import pytest
import requests

from constants import KEYWORDS
from models import ScanResult, UrlEntry
from app import (
    check_url,
    find_keywords,
    normalize_text,
    read_urls,
    scan_urls,
    to_csv_bytes,
)


class _DummyResponse:  # pylint: disable=too-few-public-methods
    """Minimal stub mimicking requests.Response for tests."""

    def __init__(self, *, status_code: int, url: str, text: str) -> None:
        """Store attributes typically inspected by the code under test."""
        self.status_code = status_code
        self.url = url
        self.text = text


class _DummySession(requests.Session):
    """Small fixture emulating the subset of Session behaviour we need."""

    def __init__(
        self, responses: Iterable[_DummyResponse], *, raise_exc: Exception | None = None
    ) -> None:
        super().__init__()
        self._responses = iter(responses)
        self._exc = raise_exc
        self.get_calls: List[str] = []
        self.closed = False

    def get(  # type: ignore[override]  # pragma: no cover - signature mirrors requests
        self, url: str, **kwargs: Any
    ) -> _DummyResponse:
        """Return the next fake response while recording the URL."""
        del kwargs
        if self._exc is not None:
            raise self._exc
        self.get_calls.append(url)
        return next(self._responses)

    def close(self) -> None:  # pragma: no cover - mirror close contract
        """Record that the session would have been closed."""
        self.closed = True


def test_find_keywords_detects_words_and_percentage() -> None:
    """Ensure keyword lookup catches accents and percentage patterns."""
    text = normalize_text("Mega Réduction -60% sur tout !")
    found = find_keywords(text, KEYWORDS)
    assert "réduction" in found
    assert "-60%" in found


def test_read_urls_filters_comments_and_blanks(tmp_path: Path) -> None:
    """The reader skips comments and empty lines while keeping order."""
    content = """
    # comment
    https://example.com

    https://promo.test
    """
    file_path = tmp_path / "urls.txt"
    file_path.write_text(content, encoding="utf-8")

    urls = read_urls(file_path)

    assert urls == [
        {"url": "https://example.com", "category": None},
        {"url": "https://promo.test", "category": None},
    ]


def test_check_url_success_detects_promo() -> None:
    """Positive scan should flag promotions and keep metadata."""
    html = "<html><body>Grande promo! -50% sur tout.</body></html>"
    session = _DummySession(
        [
            _DummyResponse(status_code=200, url="https://example.com/final", text=html),
        ]
    )

    result = check_url(session, "https://example.com")

    assert result["status"] == "ok"
    assert result["http_status"] == 200
    assert result["final_url"] == "https://example.com/final"
    assert result["has_promo"] is True
    assert "promo" in result["found"]
    assert result["changed"] is False
    assert result["category"] is None


def test_check_url_handles_http_error() -> None:
    """Non-200 responses should propagate HTTP status in the result."""
    session = _DummySession(
        [
            _DummyResponse(
                status_code=503, url="https://example.com/final", text="maintenance"
            ),
        ]
    )

    result = check_url(session, "https://example.com")

    assert result["status"] == "http_503"
    assert result["has_promo"] is False
    assert result["changed"] is False
    assert result["category"] is None


def test_check_url_handles_timeout() -> None:
    """Timeouts bubble up as a dedicated status with the error message."""
    session = _DummySession([], raise_exc=requests.exceptions.Timeout("timeout"))

    result = check_url(session, "https://example.com")

    assert result["status"] == "timeout"
    assert "timeout" in (result["error"] or "")
    assert result["changed"] is False
    assert result["category"] is None


def test_to_csv_bytes_serialises_found_entries() -> None:
    """CSV export flattens lists and keeps the changed flag."""
    rows: List[ScanResult] = [
        {
            "url": "https://example.com",
            "status": "ok",
            "http_status": 200,
            "final_url": "https://example.com/final",
            "has_promo": True,
            "found": ["promo", "-50%"],
            "error": None,
            "changed": True,
            "category": None,
        }
    ]

    csv_bytes = to_csv_bytes(rows)
    decoded = csv_bytes.decode("utf-8")

    reader = csv.DictReader(decoded.splitlines())
    row = next(reader)
    assert row["found"] == "promo, -50%"
    assert row["has_promo"] == "True"
    assert row["changed"] == "True"


def test_scan_urls_uses_custom_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """scan_urls must reuse the provided session and preserve categories."""
    responses = [
        _DummyResponse(
            status_code=200, url="https://a.example/final", text="Promo -50%"
        ),
        _DummyResponse(
            status_code=404, url="https://b.example/final", text="not found"
        ),
    ]

    dummy_session = _DummySession(responses)

    def _fake_build_session() -> _DummySession:
        """Stub factory returning our dummy session."""
        return dummy_session

    monkeypatch.setattr("scanner.build_session", _fake_build_session)

    entries: List[UrlEntry] = [
        {"url": "https://a.example", "category": "A"},
        {"url": "https://b.example", "category": "B"},
    ]

    results = scan_urls(entries, timeout=5)

    assert len(results) == 2
    assert dummy_session.get_calls == ["https://a.example", "https://b.example"]
    assert dummy_session.closed is True
    assert all(res["changed"] is False for res in results)
    assert [res["category"] for res in results] == ["A", "B"]
