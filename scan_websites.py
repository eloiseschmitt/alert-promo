import argparse
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

KEYWORDS = ["promo", "promos", "promotion", "promotions", "soldes", "remise", "réduction", "reductions","sale", "sales", "discount", "discounts", "deal", "deals", "clearance", "markdown",
    "promotion", "promotions", "offer", "offers"]

PERCENT_REGEX = re.compile(
    r"(?<!\d)(?:[3-9]0|100)\s?%|\b(?:[3-9]0|100)\s?%|\b-\s?(?:[3-9]0|100)\s?%",
    flags=re.IGNORECASE,
)

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
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "fr,fr-FR;q=0.9,en;q=0.8"})
    return session

def normalize_text(text: str) -> str:
    """Lowercase + strip + remove excessive spaces; keep accents for non-latin scripts,
    but also provide an ASCII-folded variant to match 'réduction' vs 'reduction'."""
    lowered = text.lower()
    # Version ASCII pour attraper les variantes sans accents
    ascii_folded = (
        unicodedata.normalize("NFKD", lowered)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    # On retourne les deux pour matcher plus largement
    return lowered + "\n" + ascii_folded

def extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Retirer scripts/styles/noscript
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return normalize_text(text)

def find_keywords(text: str, keywords: List[str]) -> List[str]:
    found = []
    for kw in keywords:
        # On matche naïvement en sous-chaîne (efficace pour la plupart des cas)
        if kw.lower() in text:
            found.append(kw)
    # Pourcentages
    percents = PERCENT_REGEX.findall(text)
    if percents:
        found.extend(sorted(set(p.strip() for p in percents)))
    # Dédup
    return sorted(set(found), key=str.lower)


def check_url(session: requests.Session, url: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Optional[str]]:
    original_url = url.strip()
    if not original_url:
        return {"url": original_url, "status": "skipped", "http_status": None, "final_url": None,
                "has_promo": False, "found": []}

    if not original_url.startswith(("http://", "https://")):
        url = "https://" + original_url
    else:
        url = original_url

    result: Dict[str, Optional[str] or int or bool or List[str]] = {
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

        # Vérification du code HTTP : si != 200, on le signale et on tente pas de parser
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


def read_urls(input_path: Path) -> List[str]:
    lines = input_path.read_text(encoding="utf-8").splitlines()
    # Filtrer les commentaires/vides
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]

def write_csv(output_path: Path, rows: List[Dict]):
    import csv
    fieldnames = ["url", "final_url", "http_status", "status", "has_promo", "found", "error"]
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            row = r.copy()
            # 'found' en chaîne lisible
            row["found"] = ", ".join(r.get("found", [])) if r.get("found") else ""
            writer.writerow(row)

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Vérifie la présence de mots-clés de promotions sur la page d'accueil d'une liste d'URLs."
    )
    p.add_argument("--input", "-i", required=True, help="Fichier texte avec une URL par ligne.")
    p.add_argument("--output", "-o", help="Fichier CSV de sortie (optionnel).")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Timeout HTTP en secondes (défaut: 10).")
    return p.parse_args()

def main():
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    urls = read_urls(input_path)
    if not urls:
        raise SystemExit("No URLs to process.")

    session = build_session()

    results = []
    for u in urls:
        r = check_url(session, u, timeout=args.timeout)
        results.append(r)
        # Log console succinct
        badge = "PROMO" if r.get("has_promo") else "—"
        code = r.get("http_status")
        status = r.get("status")
        print(f"[{badge}] {u}  (HTTP={code}, status={status})  found={r.get('found')}")

    if args.output:
        write_csv(Path(args.output), results)
        print(f"\nCSV écrit -> {args.output}")

if __name__ == "__main__":
    main()