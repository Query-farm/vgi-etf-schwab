"""vgi-etf-schwab: Schwab Asset Management US ETF data as DuckDB tables over VGI.

Two base tables — ``products`` (the ETF catalog) and ``holdings`` (hive-partitioned
by ``fund_ticker``, current holdings only) — backed by streaming table-function
generators. The Schwab site is fronted by Akamai and only answers a browser-TLS
fingerprint, so the network layer uses ``curl_cffi`` in-process (see
``vgi_etf_schwab.client``). The parsing logic (``vgi_etf_schwab.schwab``) is pure
and SDK-free so it can be unit-tested against injected fakes.
"""

__version__ = "0.1.0"
