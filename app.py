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

from flask import Flask, jsonify, render_template_string, send_file
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


STYLE_BLOCK = """
    :root { --bg:#0b1020; --card:#11162a; --muted:#8ea1b2; --text:#e9eef5; --accent:#2dd4bf; --warn:#f59e0b; --danger:#ef4444; --ok:#22c55e; }
    html,body { margin:0; padding:0; background:var(--bg); color:var(--text); font-family: system-ui, -apple-system, Segoe UI, Roboto, Cantarell, \"Helvetica Neue\", Arial, \"Noto Sans\", \"Apple Color Emoji\", \"Segoe UI Emoji\"; }
    .container { max-width: 1100px; margin: 40px auto; padding: 0 16px; }
    .card { background: var(--card); border: 1px solid rgba(255,255,255,.06); border-radius: 16px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,.2); }
    h1 { font-size: 28px; margin: 0 0 10px; }
    p.muted { color: var(--muted); margin-top: 0; }
    .actions { display: flex; gap: 12px; align-items: center; margin: 18px 0 8px; flex-wrap: wrap; }
    button { background: var(--accent); color:#062b2b; font-weight: 700; border: 0; padding: 10px 16px; border-radius: 12px; cursor: pointer; transition: transform .05s ease; }
    button:active { transform: translateY(1px); }
    .hint { color: var(--muted); font-size: 14px; }
    .badge { display:inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; }
    .badge.ok { background: rgba(34,197,94,.15); color: var(--ok); }
    .badge.none { background: rgba(239,68,68,.12); color: var(--danger); }
    .badge.http { background: rgba(245,158,11,.12); color: var(--warn); }
    .table-wrap { overflow:auto; border-radius: 12px; border: 1px solid rgba(255,255,255,.06); }
    table { width:100%; border-collapse: collapse; }
    th, td { padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,.06); text-align: left; font-size: 14px; }
    th { background: rgba(255,255,255,.03); position: sticky; top:0; }
    tr:hover td { background: rgba(255,255,255,.02); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", monospace; }
    .loader { display:none; margin-left: 8px; width: 18px; height: 18px; border-radius:50%; border: 2px solid rgba(255,255,255,.2); border-top-color: var(--accent); animation: spin 0.8s linear infinite; }
    .loader.show { display:inline-block; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .footer { color: var(--muted); font-size: 12px; margin-top: 10px; }
"""


TABLE_HEADER_HTML = """
            <tr>
              <th>#</th>
              <th>URL</th>
              <th>Final URL</th>
              <th>HTTP</th>
              <th>Status</th>
              <th>Promo?</th>
              <th>Found</th>
              <th>Error</th>
            </tr>
"""


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


TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>Check Promotions</title>
  <style>
""" + STYLE_BLOCK + """
  </style>
</head>
<body>
  <div class=\"container\">
    <div class=\"card\">
      <h1>🔍 Check Promotions</h1>
      <p class=\"muted\">Clique sur “Run scan” pour analyser les URLs de <span class=\"mono\">websites.txt</span> et détecter la présence de promotions (multi-langues + pourcentages).</p>
      <div class=\"actions\">
        <button id=\"runBtn\">▶︎ Run scan</button>
        <div id=\"spinner\" class=\"loader\"></div>
        <button id=\"downloadCsvBtn\" disabled>⬇️ Download CSV</button>
        <span class=\"hint\">Astuce : édite <span class=\"mono\">websites.txt</span> (une URL par ligne), puis relance le scan.</span>
      </div>

      <div class=\"table-wrap\">
        <table id=\"resultsTable\">
          <thead>
""" + TABLE_HEADER_HTML + """
          </thead>
          <tbody>
            <!-- rows injected -->
          </tbody>
        </table>
      </div>

      <div class=\"footer\">Lit <span class=\"mono\">websites.txt</span> côté serveur • Timeout {{timeout}}s • Retries: 3 • User-Agent réaliste</div>
    </div>
  </div>

  <script>
    const runBtn = document.getElementById('runBtn');
    const spinner = document.getElementById('spinner');
    const tableBody = document.querySelector('#resultsTable tbody');
    const downloadCsvBtn = document.getElementById('downloadCsvBtn');

    function statusBadge(row) {
      if (row.status === 'ok') return '<span class="badge ok">OK</span>';
      if ((row.status || '').startsWith('http_')) return '<span class="badge http">' + row.status + '</span>';
      return '<span class="badge none">' + (row.status || '—') + '</span>';
    }

    function promoBadge(row) {
      return row.has_promo ? '<span class="badge ok">PROMO</span>' : '<span class="badge none">—</span>';
    }

    function escapeHtml(s) {
      if (s == null) return '';
      return String(s).replace(/[&<>"']/g, (m) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
    }

    function renderRows(data) {
      tableBody.innerHTML = '';
      data.forEach((row, idx) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="mono">${idx + 1}</td>
          <td class="mono">${escapeHtml(row.url)}</td>
          <td class="mono">${escapeHtml(row.final_url || '')}</td>
          <td>${escapeHtml(row.http_status ?? '')}</td>
          <td>${statusBadge(row)}</td>
          <td>${promoBadge(row)}</td>
          <td>${escapeHtml((row.found || []).join(', '))}</td>
          <td class="mono">${escapeHtml(row.error || '')}</td>
        `;
        tableBody.appendChild(tr);
      });
    }

    async function runScan() {
      runBtn.disabled = true;
      spinner.classList.add('show');
      downloadCsvBtn.disabled = true;
      try {
        const res = await fetch('/scan', { method: 'POST' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        renderRows(data.results || []);
        downloadCsvBtn.disabled = (data.results || []).length === 0;
      } catch (e) {
        alert('Scan error: ' + e.message);
      } finally {
        spinner.classList.remove('show');
        runBtn.disabled = false;
      }
    }

    async function downloadCsv() {
      const res = await fetch('/download_csv', { method: 'GET' });
      if (!res.ok) {
        alert('CSV download error');
        return;
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const ts = new Date().toISOString().slice(0,19).replace(/[:T]/g,'-');
      a.download = 'results_' + ts + '.csv';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    }

    runBtn.addEventListener('click', runScan);
    downloadCsvBtn.addEventListener('click', downloadCsv);
  </script>
</body>
</html>
"""

# in-memory cache for last results to allow CSV download
LAST_RESULTS: List[ScanResult] = []


@app.route("/")
def index():
    return render_template_string(TEMPLATE, timeout=DEFAULT_TIMEOUT)


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
    # Reprend ton style et le tableau, sans les boutons/JS.
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Check Promotions – Report</title>
  <style>
{STYLE_BLOCK}
    .container {{ margin: 24px auto; padding: 0 16px; }}
    h1 {{ font-size: 22px; margin: 0 0 4px; }}
    p.muted {{ margin: 0 0 16px; }}
    th {{ position: static; }}
    .mono {{ font-size: 12px; }}
    a {{ color: var(--accent); text-decoration: none; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="card">
      <h1>🔍 Check Promotions – Rapport quotidien</h1>
      <p class="muted">Généré le {generated_at} (heure UTC). Timeout {DEFAULT_TIMEOUT}s • Retries: 3</p>

      <div class="table-wrap">
        <table role="grid" aria-label="Results">
          <thead>
{TABLE_HEADER_HTML}
          </thead>
          <tbody>
            {''.join(_render_email_row(i, r) for i, r in enumerate(results, 1))}
          </tbody>
        </table>
      </div>

      <div class="footer">Source: <span class="mono">websites.txt</span> • {len(results)} URLs vérifiées.</div>
    </div>
  </div>
</body>
</html>
"""

def _status_badge(status: Optional[str]) -> str:
    if status == "ok":
        return '<span class="badge ok">OK</span>'
    if (status or "").startswith("http_"):
        return f'<span class="badge http">{status}</span>'
    return f'<span class="badge none">{status or "—"}</span>'

def _promo_badge(has: bool) -> str:
    return '<span class="badge ok">PROMO</span>' if has else '<span class="badge none">—</span>'

def _esc(value: Optional[object]) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_email_row(idx: int, row: ScanResult) -> str:
    return f"""
    <tr>
      <td class="mono">{idx}</td>
      <td class="mono">{_esc(row['url'])}</td>
      <td class="mono">{_esc(row['final_url'])}</td>
      <td>{_esc(row['http_status'])}</td>
      <td>{_status_badge(row['status'])}</td>
      <td>{_promo_badge(row['has_promo'])}</td>
      <td>{_esc(', '.join(row['found']))}</td>
      <td class="mono">{_esc(row['error'])}</td>
    </tr>
    """

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
