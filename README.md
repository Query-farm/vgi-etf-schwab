# vgi-etf-schwab

Schwab Asset Management US ETF data as DuckDB tables, over [VGI](https://github.com/Query-farm/vgi-python)
(the Vector Gateway Interface). Two keyless base tables:

- **`products`** — the Schwab ETF catalog: one row per fund (ticker, name, tracked index,
  Morningstar category, net assets, NAV, expense ratio, holdings count, shares outstanding).
- **`holdings`** — detailed current portfolio holdings, **hive-partitioned by `fund_ticker`**
  (constituent name/ticker/CUSIP, weight %, quantity, market value). Schwab publishes
  **current holdings only**, so there is no historical/time-travel coordinate.

This is a Python VGI worker (built on `vgi-python`). It is distributed on **PyPI** — not as a
compiled binary.

## The Akamai wall → in-process `curl_cffi`

`www.schwabassetmanagement.com` is fronted by Akamai, which fingerprints the caller's TLS/JA3
handshake and returns **403** to anything that is not a real browser — plain `requests`, plain
`curl`, even `curl --http1.1`. The site answers **200** only to a client presenting Chrome's
actual TLS fingerprint. This worker therefore fetches through
[`curl_cffi`](https://github.com/lexiforest/curl_cffi), which impersonates Chrome's TLS stack
**in-process** (`requests.get(url, impersonate="chrome")`) — no subprocess, no sidecar.

Three keyless plain-text planes back the reads:

| URL | Backs |
|---|---|
| `GET /sitemap.xml` | the fund universe (every `/products/{slug}`; 4-char slugs are ETF tickers) |
| `GET /products/{ticker}` | per-fund facts (the "fund facts" table) for `products` |
| `GET /allholdings/{TICKER}` | per-fund paginated holdings for `holdings` |

## Use from DuckDB

```sql
LOAD vgi;
ATTACH 'schwab' AS schwab (TYPE vgi, LOCATION '/path/to/vgi-etf-schwab/bin/vgi-etf-schwab-worker');

-- The ETF catalog (a base table — no arguments; filter with WHERE):
SELECT ticker, fund_name, net_assets FROM schwab.main.products ORDER BY net_assets DESC LIMIT 10;

-- One fund's current holdings (the fund_ticker filter is pushed into the scan):
SELECT name, ticker, weight_percent
FROM schwab.main.holdings WHERE fund_ticker = 'SCHD'
ORDER BY weight_percent DESC LIMIT 10;

-- Two funds at once (partition fan-out); an unfiltered scan streams every fund:
SELECT fund_ticker, name, weight_percent FROM schwab.main.holdings WHERE fund_ticker IN ('SCHD','SCHF');
```

`percent` columns (`expense_ratio_percent`, `weight_percent`, …) hold **percent points**
(`0.06` = 0.06%, `4.49` = 4.49%). `market_value` is abbreviated on Schwab's page (`$4.4B`), so it
is approximate.

## Run as a container

A multi-arch (linux/amd64 + linux/arm64), cosign-signed image is published to
`ghcr.io/query-farm/vgi-etf-schwab` on every release — no local Python or `uv` needed. Attach it
directly over the VGI container transport:

```sql
LOAD vgi;
ATTACH 'schwab' AS schwab (TYPE vgi, LOCATION 'oci://ghcr.io/query-farm/vgi-etf-schwab:latest');
```

Or run the HTTP transport yourself and attach that:

```bash
docker run --rm -p 8000:8000 ghcr.io/query-farm/vgi-etf-schwab:latest   # serves /health + the VGI RPC on :8000
```

```sql
LOAD vgi;
ATTACH 'schwab' AS schwab (TYPE vgi, LOCATION 'http://localhost:8000');
```

`:latest` always tracks the newest release.

## Development

```bash
uv sync --extra dev          # install the environment (vgi-python + curl_cffi + pyarrow)
uv run pytest -q             # unit tests: SDK-free driver + Arrow batch builders (injected fakes, no network)
uv run ruff check . && uv run ruff format --check .
uv run mypy vgi_etf_schwab/
./run_tests.sh               # haybarn SQLLogic E2E: the worker under real DuckDB + the community vgi extension (hits Schwab live)
```

Metadata-quality gate (deterministic, no network):

```bash
uvx --prerelease allow --from vgi-lint-check vgi-lint bin/vgi-etf-schwab-worker --fail-on info --no-execute
```

## Layout

- `vgi_etf_schwab/schwab.py` — the **pure driver**: URL builders + HTML/XML parsers, SDK-free,
  driven by an injected `get(url) -> str`. This is what the unit tests exercise.
- `vgi_etf_schwab/client.py` — the **only network module**: the in-process `curl_cffi` transport
  (Chrome impersonation) + a 24 h sitemap cache; injectable for tests.
- `vgi_etf_schwab/schema.py` — typed pyarrow schemas + row→batch builders (real DATE, `_percent` points).
- `vgi_etf_schwab/functions.py` — the two `TableFunctionGenerator`s (products one-shot scan;
  holdings partitioned queue scan with filter pushdown).
- `vgi_etf_schwab/catalog.py` — the declarative `Catalog` descriptor + all `vgi.*` metadata tags.
- `vgi_etf_schwab/worker.py` — the `Worker` subclass + `main()` (stdio entry).
- `bin/vgi-etf-schwab-worker` — the executable DuckDB `ATTACH`es (a wrapper around `uv run`).

Data is Schwab's public fund website: best-effort, for informational use. Review Schwab's terms
before redistribution.
