"""Approval tests for HTML outputs produced by app.py."""

from __future__ import annotations

from typing import List

from approvaltests import verify_html
from flask import render_template

from constants import DEFAULT_TIMEOUT
from models import ScanResult
from app import app as flask_app, render_email_html


def _sample_results() -> List[ScanResult]:
    return [
        {
            "url": "https://example.com",
            "status": "ok",
            "http_status": 200,
            "final_url": "https://example.com/promotions",
            "has_promo": True,
            "found": ["promo", "50%"],
            "error": None,
        },
        {
            "url": "https://slow-shop.test",
            "status": "timeout",
            "http_status": 504,
            "final_url": "https://slow-shop.test",
            "has_promo": False,
            "found": [],
            "error": "Timeout of 10s exceeded",
        },
    ]


def _render_index_html() -> str:
    with flask_app.app_context():
        with flask_app.test_request_context("/"):
            return render_template("index.html", timeout=DEFAULT_TIMEOUT)


def test_index_template_matches_snapshot() -> None:
    """Rendered dashboard HTML should stay stable."""
    html = _render_index_html()
    verify_html(html)


def test_email_template_matches_snapshot() -> None:
    """Email rendering must keep expected markup structure."""
    html = render_email_html(_sample_results(), generated_at="2024-01-01T00:00:00Z")
    verify_html(html)
