# vgi-etf-schwab

Schwab Asset Management US ETF data as DuckDB tables, over [VGI](https://github.com/Query-farm/vgi-python)
(the Vector Gateway Interface). Two keyless base tables:

- **`products`** — the Schwab ETF catalog: one row per fund (ticker, name, tracked index,
  Morningstar category, net assets, NAV, expense ratio, holdings count, shares outstanding).
- **`holdings`** — detailed current portfolio holdings, **hive-partitioned by `fund_ticker`**
  (constituent name/ticker/CUSIP, weight %, quantity, market value). Schwab publishes
  **current holdings only**, so there is no historical/time-travel coordinate.

This is a Python VGI worker (built on `vgi-python`). It runs with `uvx` straight from a tagged
GitHub release, or from the published container image — not as a compiled binary.

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

## Quick start

The worker isn't on PyPI; [uv](https://docs.astral.sh/uv/) runs it straight from a tagged release on GitHub. `uvx` builds an isolated environment on the first ATTACH and reuses it afterwards:

```sql
INSTALL vgi FROM community;
LOAD vgi;

ATTACH 'schwab' AS schwab (TYPE vgi, LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-etf-schwab@v0.4.0 vgi-etf-schwab-worker');

-- The largest Schwab ETFs by net assets
SELECT ticker, fund_name, net_assets FROM schwab.main.products ORDER BY net_assets DESC LIMIT 5;

-- The top holdings of the Schwab U.S. Dividend Equity ETF
SELECT name, ticker, weight_percent FROM schwab.main.holdings WHERE fund_ticker = 'SCHD' ORDER BY weight_percent DESC LIMIT 5;

-- Combine the tables: how concentrated each large-cap fund is (share in its top 10 positions) vs what it costs
WITH ranked AS (
    SELECT fund_ticker, weight_percent,
           row_number() OVER (PARTITION BY fund_ticker ORDER BY weight_percent DESC) AS rn
    FROM schwab.main.holdings WHERE fund_ticker IN ('SCHD', 'SCHG', 'SCHV', 'SCHX')
)
SELECT p.ticker, p.fund_name, p.expense_ratio_percent, count(*) AS num_positions,
       round(sum(r.weight_percent) FILTER (WHERE r.rn <= 10), 2) AS top10_weight_percent
FROM ranked r JOIN schwab.main.products p ON p.ticker = r.fund_ticker
GROUP BY ALL ORDER BY top10_weight_percent DESC;
```

`percent` columns (`expense_ratio_percent`, `weight_percent`, …) hold **percent points**
(`0.06` = 0.06%, `4.49` = 4.49%). `market_value` is abbreviated on Schwab's page (`$4.4B`), so it
is approximate. The `fund_ticker` filter on `holdings` is pushed into the scan; an `IN (...)` list
fans out across partitions, and an unfiltered scan streams every fund. Name the funds literally
when joining `holdings` to `products`: the filter is pushed down only as a literal `=` / `IN (...)`
list, not through the join or an `IN (SELECT ...)` subquery. No credentials are needed.

Change `@v0.4.0` to move to a newer release.

### Other ways to run it

- **Docker** (the image bundles the worker and its dependencies; multi-arch linux/amd64 +
  linux/arm64, cosign-signed, published to `ghcr.io/query-farm/vgi-etf-schwab` on every release —
  no local Python or `uv` needed):

  ```sql
  ATTACH 'schwab' AS schwab (TYPE vgi, LOCATION 'docker://ghcr.io/query-farm/vgi-etf-schwab:0.4.0');
  ```

- **Over HTTP**: run the image's HTTP transport yourself and attach that:

  ```bash
  docker run --rm -p 8000:8000 ghcr.io/query-farm/vgi-etf-schwab:0.4.0   # serves /health + the VGI RPC on :8000
  ```

  ```sql
  ATTACH 'schwab' AS schwab (TYPE vgi, LOCATION 'http://localhost:8000');
  ```

  `:latest` always tracks the newest release.

- **From a local checkout** (`git clone https://github.com/Query-farm/vgi-etf-schwab`), point `LOCATION` at `uv run --project /path/to/vgi-etf-schwab vgi-etf-schwab-worker`.

### Build from source

To build and test the worker yourself, see [Development](#development).

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
uvx --prerelease allow --from 'vgi-lint-check>=2.0.1,<3' vgi-lint bin/vgi-etf-schwab-worker --fail-on info --no-execute
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

## Executed notebook

Explore [CUSIP overlap, shared weights and pagination checks](notebooks/README.md) with recorded and live holdings.
