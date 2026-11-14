"""Wire the released worker to exact recorded pages or its official live client."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from vgi import Worker
from vgi_etf_schwab.catalog import make_catalog
from vgi_etf_schwab.client import make_schwab_get
from vgi_etf_schwab.functions import make_holdings_scan, make_products_scan
from vgi_etf_schwab.schwab import parse_holdings_page

mode = os.environ.get("NOTEBOOK_SCHWAB_DATA_MODE")
if mode not in ("recorded", "live"):
    raise ValueError("Choose recorded or live in the notebook")
audit = Path(os.environ["NOTEBOOK_SCHWAB_AUDIT"])
responses = {}
if mode == "recorded":
    directory = Path(os.environ["NOTEBOOK_SCHWAB_RECORDINGS"])
    for record in json.loads((directory / "manifest.json").read_text())["records"]:
        data = (directory / record["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("Recorded response hash mismatch")
        responses[record["url"]] = data.decode("utf-8")
live_get = make_schwab_get() if mode == "live" else None


def fetch(url: str) -> str:
    """Return text and audit page coverage using the released parser itself."""
    parts = urlparse(url)
    if parts.netloc != "www.schwabassetmanagement.com" or not parts.path.startswith("/allholdings/"):
        raise ValueError("This walkthrough is bounded to holdings pages")
    fund = parts.path.rsplit("/", 1)[1]
    if fund not in ("SCHD", "SCHV"):
        raise ValueError("This walkthrough is bounded to SCHD and SCHV")
    row = {"fund_ticker": fund, "page": int(parse_qs(parts.query).get("page", [0])[0]), "url": url}
    try:
        text = live_get(url) if live_get else responses[url]
        parsed = parse_holdings_page(text, fund)
        row.update(
            ok=True,
            parsed_rows=len(parsed.rows),
            advertised_total=parsed.total,
            source_date=parsed.as_of.isoformat() if parsed.as_of else None,
        )
    except Exception:
        row.update(ok=False, parsed_rows=0, advertised_total=None, source_date=None)
        raise
    finally:
        with audit.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
    return text


get = make_schwab_get(fetch=fetch)


class RecordedSchwabWorker(Worker):
    """Real released functions/catalog with an explicit transport selection."""

    catalog = make_catalog(make_products_scan(get), make_holdings_scan(get))


if __name__ == "__main__":
    RecordedSchwabWorker().run()
