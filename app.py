#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, TypedDict, cast
import datetime
import io
import os
import re
import smtplib
import unicodedata

from flask import Flask, jsonify, render_template, send_file
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import csv

from email.message import EmailMessage

app = Flask(__name__)

# ----------------- Config -----------------
DEFAULT_TIMEOUT = 10
URLS_FILE = Path("websites.txt")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

KEYWORDS: List[str] = [
    "promo", "promos", "promotion", "promotions", "soldes", "remise", "réduction", "reductions",
    "sale", "sales", "discount", "discounts", "deal", "deals", "clearance", "markdown",
    "promotion", "promotions", "offers"
]

PERCENT_REGEX = re.compile(
    r"-?\s?(?:50|60|70)\s?%",
    flags=re.IGNORECASE,
)


class ScanResult(TypedDict):
    url: str
    status: Optional[str]
    http_status: Optional[int]
    final_url: Optional[str]
    has_promo: bool
    found: List[str]
    error: Optional[str]


# ----------------- HTTP session -----------------
def build_session() -> requests.Session:
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
        "Accept-Language": "fr,fr-FR;q=0.9,en;q=0.8"
    })
    return session


# ----------------- Utilities -----------------
def normalize_text(text: str) -> str:
    lowered = text.lower()
    ascii_folded = (
        unicodedata.normalize("NFKD", lowered)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return lowered + "\n" + ascii_folded


def extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return normalize_text(text)


def find_keywords(text: str, keywords: List[str]) -> List[str]:
    found = []
    for kw in keywords:
        if kw.lower() in text:
            found.append(kw)
    percents = PERCENT_REGEX.findall(text)
    if percents:
        found.extend(sorted(set(p.strip() for p in percents)))
    return sorted(set(found), key=str.lower)


def read_urls(input_path: Path) -> List[str]:
    if not input_path.exists():
        return []
    lines = input_path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _make_empty_result(url: str) -> ScanResult:
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
    if not urls:
        return []

    session = build_session()
    try:
        return [check_url(session, candidate, timeout=timeout) for candidate in urls]
    finally:
        session.close()


# in-memory cache for last results to allow CSV download
LAST_RESULTS: List[ScanResult] = []


@app.route("/")
def index():
    return render_template("index.html", timeout=DEFAULT_TIMEOUT)


@app.route("/scan", methods=["POST"])
def scan():
    global LAST_RESULTS
    urls = read_urls(URLS_FILE)
    results = scan_urls(urls, timeout=DEFAULT_TIMEOUT)
    LAST_RESULTS = list(results)
    return jsonify({"results": results})


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


# ---------- Batch scan (reusable) ----------
def run_batch_scan(timeout: int = DEFAULT_TIMEOUT) -> List[ScanResult]:
    urls = read_urls(URLS_FILE)
    return scan_urls(urls, timeout=timeout)

# ---------- HTML rendering for email ----------
def render_email_html(results: Sequence[ScanResult], generated_at: str) -> str:
    template = app.jinja_env.get_template("email_report.html")
    return template.render(
        results=results,
        generated_at=generated_at,
        default_timeout=DEFAULT_TIMEOUT,
    )

# ---------- SMTP email ----------
def send_email(subject: str, html_body: str, to_addrs: List[str]) -> None:
    """
    Uses ENV for SMTP settings:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM
    """
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    mail_from = os.getenv("MAIL_FROM")

    if not smtp_host or not mail_from:
        raise RuntimeError("SMTP configuration missing: SMTP_HOST/MAIL_FROM")
    if not to_addrs:
        raise RuntimeError("No recipients provided to send_email")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(to_addrs)

    # Plain-text fallback (minimale)
    msg.set_content("Votre client email ne supporte pas le HTML. Ouvrez ce message en HTML pour voir le rapport.")
    # HTML body
    msg.add_alternative(html_body, subtype="html")

    # TLS sur 587 par défaut
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        try:
            server.starttls()
            server.ehlo()
        except smtplib.SMTPException:
            pass  # serveur déjà en TLS ou TLS non supporté
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.send_message(msg)

# ---------- CLI entry ----------
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
