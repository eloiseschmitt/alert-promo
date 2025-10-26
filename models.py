"""Data structures used across the application."""

from __future__ import annotations

from typing import List, Optional, TypedDict


class ScanResult(TypedDict):
    url: str
    status: Optional[str]
    http_status: Optional[int]
    final_url: Optional[str]
    has_promo: bool
    found: List[str]
    error: Optional[str]


__all__ = ["ScanResult"]
