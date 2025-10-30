"""Data structures used across the application."""

from __future__ import annotations

from typing import List, Optional, TypedDict


class ScanResult(TypedDict):
    """Structured result returned after inspecting a single URL."""

    url: str
    status: Optional[str]
    http_status: Optional[int]
    final_url: Optional[str]
    has_promo: bool
    found: List[str]
    error: Optional[str]
    changed: bool
    category: Optional[str]


class UrlEntry(TypedDict):
    """An entry read from websites.txt including optional category."""

    url: str
    category: Optional[str]


__all__ = ["ScanResult"]
