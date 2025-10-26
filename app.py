#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from typing import Sequence
import datetime
import io
import os

from flask import Flask, jsonify, render_template, send_file

import constants
from constants import DEFAULT_TIMEOUT, KEYWORDS, PERCENT_REGEX, URLS_FILE, USER_AGENT, LAST_RESULTS
from models import ScanResult
import scanner
from email_service import render_email_html as _render_email_html, send_email


build_session = scanner.build_session
normalize_text = scanner.normalize_text
extract_visible_text = scanner.extract_visible_text
find_keywords = scanner.find_keywords
read_urls = scanner.read_urls
check_url = scanner.check_url
to_csv_bytes = scanner.to_csv_bytes
scan_urls = scanner.scan_urls
run_batch_scan = scanner.run_batch_scan

app = Flask(__name__)

__all__ = [
    "DEFAULT_TIMEOUT",
    "URLS_FILE",
    "USER_AGENT",
    "KEYWORDS",
    "PERCENT_REGEX",
    "ScanResult",
    "build_session",
    "normalize_text",
    "extract_visible_text",
    "find_keywords",
    "read_urls",
    "check_url",
    "to_csv_bytes",
    "scan_urls",
    "run_batch_scan",
    "render_email_html",
    "send_email",
    "app",
]


@app.route("/")
def index():
    return render_template("index.html", timeout=DEFAULT_TIMEOUT)


@app.route("/scan", methods=["POST"])
def scan():
    urls = read_urls(URLS_FILE)
    promo_results = scan_urls(urls, timeout=DEFAULT_TIMEOUT)
    constants.LAST_RESULTS = list(promo_results)
    return jsonify({"results": promo_results})


@app.route("/download_csv", methods=["GET"])
def download_csv():
    csv_bytes = to_csv_bytes(LAST_RESULTS or [])
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    mem = io.BytesIO(csv_bytes)
    mem.seek(0)
    return send_file(
        mem,
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=f"results_{ts}.csv",
    )


def render_email_html(results: Sequence[ScanResult], generated_at: str) -> str:
    return _render_email_html(results, generated_at, env=app.jinja_env)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--batch":
        output = Path("data/results.csv")
        output.parent.mkdir(parents=True, exist_ok=True)
        results = run_batch_scan()
        output.write_bytes(to_csv_bytes(results))
        print(f"[OK] Results written to {output} ({len(results)} URLs)")

    elif len(sys.argv) > 1 and sys.argv[1] == "--email":
        # recipients from CLI or ENV MAIL_TO (comma-separated)
        to_env = os.getenv("MAIL_TO", "")
        to_arg = sys.argv[2] if len(sys.argv) > 2 else ""
        to_list = [e.strip() for e in (to_arg or to_env).split(",") if e.strip()]
        if not to_list:
            raise SystemExit("No recipients provided. Use: python app.py --email you@example.com OR set MAIL_TO env.")

        results = run_batch_scan()
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
        html = render_email_html(results, generated_at=ts)
        send_email(subject=f"Check Promotions – Rapport {ts}", html_body=html, to_addrs=to_list)
        print(f"[OK] Email sent to: {', '.join(to_list)} ({len(results)} URLs)")

    else:
        app.run(host="0.0.0.0", port=8080, debug=True)
