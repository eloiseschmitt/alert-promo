#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from typing import Dict, List, Optional
import re
import unicodedata

from flask import Flask, jsonify, render_template_string, send_file
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import csv
import io
import datetime

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


def check_url(session: requests.Session, url: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Optional[str]]:
    original_url = url.strip()
    if not original_url:
        return {
            "url": original_url, "status": "skipped", "http_status": None,
            "final_url": None, "has_promo": False, "found": [], "error": None
        }

    if not original_url.startswith(("http://", "https://")):
        url = "https://" + original_url
    else:
        url = original_url

    result = {
        "url": original_url,
        "status": None,
        "http_status": None,
        "final_url": None,
        "has_promo": False,
        "found": [],
        "error": None,
    }

    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
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

    except requests.exceptions.SSLError as e:
        result["status"] = "ssl_error"
        result["error"] = str(e)
    except requests.exceptions.Timeout as e:
        result["status"] = "timeout"
        result["error"] = str(e)
    except requests.exceptions.RequestException as e:
        result["status"] = "request_error"
        result["error"] = str(e)

    return result


def to_csv_bytes(rows: List[Dict]) -> bytes:
    output = io.StringIO()
    fieldnames = ["url", "final_url", "http_status", "status", "has_promo", "found", "error"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        row = r.copy()
        row["found"] = ", ".join(r.get("found", [])) if r.get("found") else ""
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


# ----------------- Web UI -----------------
TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Check Promotions</title>
  <style>
    :root { --bg:#0b1020; --card:#11162a; --muted:#8ea1b2; --text:#e9eef5; --accent:#2dd4bf; --warn:#f59e0b; --danger:#ef4444; --ok:#22c55e; }
    html,body { margin:0; padding:0; background:var(--bg); color:var(--text); font-family: system-ui, -apple-system, Segoe UI, Roboto, Cantarell, "Helvetica Neue", Arial, "Noto Sans", "Apple Color Emoji", "Segoe UI Emoji"; }
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
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }
    .loader { display:none; margin-left: 8px; width: 18px; height: 18px; border-radius:50%; border: 2px solid rgba(255,255,255,.2); border-top-color: var(--accent); animation: spin 0.8s linear infinite; }
    .loader.show { display:inline-block; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .footer { color: var(--muted); font-size: 12px; margin-top: 10px; }
  </style>
</head>
<body>
  <div class="container">
    <div class="card">
      <h1>🔍 Check Promotions</h1>
      <p class="muted">Clique sur “Run scan” pour analyser les URLs de <span class="mono">websites.txt</span> et détecter la présence de promotions (multi-langues + pourcentages).</p>
      <div class="actions">
        <button id="runBtn">▶︎ Run scan</button>
        <div id="spinner" class="loader"></div>
        <button id="downloadCsvBtn" disabled>⬇️ Download CSV</button>
        <span class="hint">Astuce : édite <span class="mono">websites.txt</span> (une URL par ligne), puis relance le scan.</span>
      </div>

      <div class="table-wrap">
        <table id="resultsTable">
          <thead>
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
          </thead>
          <tbody>
            <!-- rows injected -->
          </tbody>
        </table>
      </div>

      <div class="footer">Lit <span class="mono">websites.txt</span> côté serveur • Timeout {{timeout}}s • Retries: 3 • User-Agent réaliste</div>
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
LAST_RESULTS: List[Dict] = []


@app.route("/")
def index():
    return render_template_string(TEMPLATE, timeout=DEFAULT_TIMEOUT)


@app.route("/scan", methods=["POST"])
def scan():
    global LAST_RESULTS
    urls = read_urls(URLS_FILE)
    session = build_session()
    results = []
    for u in urls:
        r = check_url(session, u, timeout=DEFAULT_TIMEOUT)
        results.append(r)
    LAST_RESULTS = results
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
