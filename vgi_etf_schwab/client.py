"""The real Schwab Asset Management HTTP client — the ONE module that touches the network.

THE AKAMAI WALL (why this client is unusual). ``www.schwabassetmanagement.com`` is
fronted by Akamai, which fingerprints the caller's TLS/JA3 handshake and returns **403**
to anything that is not a real browser — plain ``requests``, plain ``curl``, and even
``curl --http1.1`` are ALL rejected. The site answers **200** only to a client presenting
Chrome's actual TLS fingerprint. So this client fetches through ``curl_cffi``, a Python
library that impersonates Chrome's TLS stack IN-PROCESS (no sidecar, no subprocess):

    from curl_cffi import requests
    requests.get(url, impersonate="chrome", timeout=30)

The pure driver (:mod:`vgi_etf_schwab.schwab`) takes an injected ``get(url) -> str``; the
worker wires :func:`make_schwab_get` (the real ``curl_cffi`` transport) and the unit tests
inject an in-process fake, so they never touch the network.

SITEMAP CACHE: the ``sitemap.xml`` backs the fund universe (every ``products`` scan and
every ticker resolution) and changes at most once a day. The client memoizes just that one
URL with a 24 h TTL (shared across queries in a long-lived worker process). Product and
holdings pages always go live.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from vgi_etf_schwab.schwab import SITEMAP_URL

#: Default sitemap cache lifetime: 24 hours, in seconds.
CATALOG_CACHE_SECONDS = 24 * 60 * 60

#: The chrome fingerprint empirically verified to pass Schwab's Akamai front (200, not 403).
IMPERSONATE = "chrome"

#: Per-request timeout, in seconds.
TIMEOUT_SECONDS = 30

Getter = Callable[[str], str]


def _curl_cffi_get(url: str) -> str:
    """Fetch ``url`` through ``curl_cffi`` with a Chrome TLS fingerprint; raise on non-2xx."""
    from curl_cffi import requests  # imported lazily so the driver/tests stay import-light

    # IMPERSONATE ("chrome") is passed as a literal so curl_cffi's typed overloads accept it.
    response = requests.get(url, impersonate="chrome", timeout=TIMEOUT_SECONDS)
    status = response.status_code
    if status < 200 or status >= 400:
        body = (response.text or "")[:200]
        raise RuntimeError(f"schwab: HTTP {status} for {url} — {body}")
    text = response.text
    return text if isinstance(text, str) else str(text)


def make_schwab_get(
    fetch: Getter | None = None,
    *,
    catalog_cache_seconds: int = CATALOG_CACHE_SECONDS,
    now: Callable[[], float] = time.monotonic,
) -> Getter:
    """Build the injectable ``get(url) -> str`` transport used by the table functions.

    Args:
        fetch: The underlying single-URL fetcher. Defaults to the real ``curl_cffi``
            transport; the unit tests pass a fake so no network is touched.
        catalog_cache_seconds: Sitemap cache TTL in seconds. Pass ``0`` to disable caching.
        now: Injectable monotonic clock (seconds) — for tests.

    Returns:
        A ``get`` that memoizes the sitemap for the TTL and passes every other URL through.
    """
    raw = fetch if fetch is not None else _curl_cffi_get
    cache: dict[str, tuple[float, str]] = {}

    def get(url: str) -> str:
        if catalog_cache_seconds > 0 and url == SITEMAP_URL:
            hit = cache.get(url)
            t = now()
            if hit is not None and t - hit[0] < catalog_cache_seconds:
                return hit[1]
            value = raw(url)
            cache[url] = (t, value)
            return value
        return raw(url)

    return get
