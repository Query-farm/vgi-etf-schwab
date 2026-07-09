"""vgi-etf-schwab stdio worker entry.

DuckDB spawns this and ATTACHes it::

    LOAD vgi;
    ATTACH 'schwab' AS schwab (TYPE vgi, LOCATION '/path/to/bin/vgi-etf-schwab-worker');
    SELECT * FROM schwab.main.products ORDER BY net_assets DESC LIMIT 10;
    SELECT * FROM schwab.main.holdings WHERE fund_ticker = 'SCHD' ORDER BY weight_percent DESC LIMIT 10;

Keyless: no CREATE SECRET is needed. ``products`` and ``holdings`` are base TABLES (backed
by scan functions); ``holdings_scan`` is also listed so the extension can push the
``fund_ticker`` filter into the ``holdings`` table. All functions take the injected
``curl_cffi`` HTTP transport (:mod:`vgi_etf_schwab.client`), which reaches the
Akamai-fronted Schwab site in-process with a Chrome TLS fingerprint.
"""

from __future__ import annotations

from vgi import Worker

from vgi_etf_schwab.catalog import make_catalog
from vgi_etf_schwab.client import make_schwab_get
from vgi_etf_schwab.functions import make_holdings_scan, make_products_scan

# Wire the real (impersonating) HTTP transport into the backing scans, then build the
# declarative catalog. No network happens at import (schema derivation is bind-only).
_get = make_schwab_get()
_products_scan = make_products_scan(_get)
_holdings_scan = make_holdings_scan(_get)


class SchwabWorker(Worker):
    """The VGI worker hosting the ``schwab`` catalog (products + holdings)."""

    catalog = make_catalog(_products_scan, _holdings_scan)


def main() -> None:
    """Run the Schwab worker over stdio (Arrow IPC on stdin/stdout)."""
    SchwabWorker().run()


if __name__ == "__main__":
    main()
