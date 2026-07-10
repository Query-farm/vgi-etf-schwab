# vgi-etf-schwab — agent notes

A VGI (DuckDB) worker exposing **Schwab Asset Management** US ETF data as two base **tables** —
`products` (the catalog) and `holdings` (hive-partitioned, current-only) — plus the one listed
backing scan `holdings_scan`. **Python, built on `vgi-python`** (the Python VGI SDK), run with
`uv`. Keyless — no secret type, no auth. Distributed on **PyPI**, NOT a compiled binary.

## THE AKAMAI WALL — the whole reason this worker is unusual

`www.schwabassetmanagement.com` is fronted by **Akamai**, which fingerprints the caller's
**TLS/JA3 handshake** and returns **403** to anything that is not a real browser. Confirmed
empirically: plain `requests` → 403, plain `curl` → 403, `curl --http1.1` → 403. The site answers
**200** only to a client presenting Chrome's actual TLS fingerprint.

The fix is **`curl_cffi`** (`from curl_cffi import requests; requests.get(url, impersonate="chrome")`),
a Python library that impersonates Chrome's TLS stack **IN-PROCESS** — no subprocess, no sidecar.
This is the entire reason the worker is Python and not the sibling TS stack (Bun can't do a Chrome
TLS fingerprint in-process). The transport lives in `client.py` (`make_schwab_get`); it is the ONLY
network module. **If Akamai rate-limits the IP you'll see 403** — the static gates (pytest, mypy,
ruff, vgi-lint `--no-execute`) are all network-free; only the haybarn live-invariant asserts hit
Schwab.

## Architecture (keep this separation)

- **`vgi_etf_schwab/schwab.py` — the pure driver.** URL builders + HTML/XML parsers, plus
  `fetch_*` orchestrators and `resolve_fund`, all taking an injected `get(url) -> str`. NO network,
  NO SDK import (imports only stdlib). This is what the unit tests exercise. Parsing is defensive:
  a missing field/row/page degrades to `[]` / `None`, never a raise. `resolve_fund` returns
  `str | None` (None = ticker not found) rather than raising, so this module stays SDK-free.
  Dates are parsed to real `datetime.date` (the Arrow DATE mapping lives in `schema.py`).
- **`vgi_etf_schwab/client.py` — the only network module.** `make_schwab_get()` returns the real
  `get` (curl_cffi, Chrome impersonation) with a 24 h **sitemap** cache. Inject a fake `fetch` to
  disable the network (the unit tests do this). No dedicated unit test beyond the cache/injection
  test; exercised live by haybarn.
- **`vgi_etf_schwab/schema.py` — typed pyarrow schemas + batch builders.** Real typed columns
  (`string`/`float64`/`int64`/`date32`). Every calendar date is a real Arrow **DATE** (`date32` →
  DuckDB `DATE`, no timezone). `products_columns` / `holdings_columns` build column dicts consumed
  by `pa.RecordBatch.from_pydict`. Percent columns carry a `_percent` suffix and hold **percent
  points** (`weight_percent` 4.49 = 4.49%; `expense_ratio_percent` 0.06 = 0.06%). `result_columns_schema`
  builds the `vgi.result_columns_schema` tag from the Arrow schema. `fund_ticker` is marked with
  `partition_field(...)` (`vgi.partition_column`) — the hive partition key.
- **`vgi_etf_schwab/functions.py`** — two `TableFunctionGenerator` classes built by FACTORIES that
  close over the injected `get` (the framework uses classmethods, so a factory closure is how the
  client is injected — `make_products_scan(get)` / `make_holdings_scan(get)`).
- **`vgi_etf_schwab/catalog.py` / `worker.py`** — the declarative `Catalog` descriptor (all `vgi.*`
  tags) and the `Worker` subclass + `main()` entry (`SchwabWorker().run()`).

## The two tables — two layers: registry vs listing

`products` and `holdings` are **function-backed base tables** (`Table(function=...)` in the
declarative `Catalog`). Two INDEPENDENT layers matter (mirrors the TS sibling):

- **Worker function registry** — the *dispatch* layer. `Worker._build_registry` auto-registers
  every `Table.function` (so both `products_scan` and `holdings_scan` are dispatchable) PLUS every
  function in `Schema.functions`.
- **`Schema.functions`** — the *listing* layer. Controls what shows as a callable `X()` function
  AND is where the extension discovers a scan's `filter_pushdown` capability.

`products_scan` is **registered (via `Table.function`) but NOT listed** → exposed only as the
`products` table. `holdings_scan` MUST be **listed** (`Schema(functions=[holdings_scan])`) — an
unlisted backing scan gets **no** pushdown (the extension can't see its `filter_pushdown`
capability), so the `fund_ticker` partition filter never reaches it. A visible
`holdings_scan` function is therefore unavoidable; it takes an **optional `fund_ticker`
argument** (`holdings_scan(fund_ticker => 'SCHD')` fetches one fund directly; omitting it
streams every fund / accepts the pushed-down filter), so it is not parameterless (VGI311
needs no waiver).

## `holdings` — hive-partitioned by `fund_ticker`, current-only (NO time travel)

Query `FROM schwab.main.holdings WHERE fund_ticker = 'SCHD'` for one fund; `IN (…)` fans out;
an **unfiltered scan streams every fund** (one partition per fund). Mechanics (all verified under
haybarn against live Schwab):

- **`Meta.partition_kind = SINGLE_VALUE_PARTITIONS`** + `fund_ticker` marked with
  `partition_field(...)` → each emitted batch is one SINGLE_VALUE partition. Partition values are
  auto-extracted from the emitted batch (which always carries the full `FIXED_SCHEMA`, including
  `fund_ticker`) — the pattern from `vgi/_test_fixtures/table/partition_columns.py`.
- **BoundStorage work queue.** `on_init` (runs once on the coordinator) reads the pushed
  `fund_ticker` filter via `cls.pushdown_filters(pf, join_keys).get_column_values("fund_ticker")`
  (equality/IN), or — absent one — the whole ETF universe from the sitemap, and
  `params.storage.queue_push`es one item per fund. `process()` `queue_pop`s one fund per tick,
  fetches its holdings, and `out.emit`s a single partition batch. `max_workers` (`HOLDINGS_MAX_WORKERS`,
  4 — kept modest to stay gentle on Akamai) drains the same queue → work-stealing fan-out.
  `LIMIT` short-circuits the stream.
- **`Meta.filter_pushdown = True`** + LISTED → the extension pushes the `fund_ticker` filter into
  the scan. Empty/skipped funds (a non-ETF slug or empty page) are popped-and-skipped in a loop.
- **NO time travel / no as-of argument** — Schwab publishes CURRENT holdings only; `as_of_date` is
  the page's own "as of" date. (Unlike the sibling iShares worker, there is no `AT (…)`.)
- **`fund_ticker` is a SEPARATE column from `ticker`** — `ticker` is the CONSTITUENT's own ticker.
  `products` advisory PK `[ticker]`; `holdings` has an advisory composite PK
  `(fund_ticker, cusip)` — both NOT NULL (cash / derivative lines with no CUSIP are emitted
  as `""`, never NULL), which identifies each constituent within a fund and satisfies
  VGI807/809 for real. No cross-table FK (ticker/cusip recur with different meanings).

## Schwab endpoint facts (why the design is what it is)

Three keyless plain-text (Drupal HTML/XML) planes, all needing only the Chrome TLS fingerprint:

1. **`/sitemap.xml`** → the fund UNIVERSE. `parse_universe` keeps every `/products/{slug}` whose
   slug is a 4-char alphanumeric (Schwab ETF tickers are 4 letters; mutual/money-market funds are
   5), upper-cased, minus a few section slugs. A superset — non-ETF candidates are dropped later.
2. **`/products/{ticker}`** → per-fund FACTS. `parse_product` finds the one `<table>` carrying both
   "CUSIP" and "Total Net Assets"; each row is `<th>Label</th> … <td>Value</td>` (value = last td;
   an "As of …" date may ride in the label). Fund name from the `<title>`
   (`TICKER | Fund Name | Schwab Asset Management`). No facts table → `None` (dropped).
3. **`/allholdings/{TICKER}`** → per-fund paginated HOLDINGS. `parse_holdings_page` finds the table
   whose header carries "% of Assets" (header-driven so a reordered column set still binds), reads
   the "As of MM/DD/YY" date and the "Displaying x - y of N" total, and pages via `?page=N`.
   `market_value` is abbreviated (`$4.4B`) → `parse_abbrev_money` (approximate). Rows are sorted
   weight-DESC (NULLS last), so `… LIMIT n` returns the top holdings without ORDER BY. A transport
   error on page 0 is PROPAGATED (a 403 must not masquerade as an empty fund); later pages are
   best-effort.

## Launch mechanism

`bin/vgi-etf-schwab-worker` (executable) is what DuckDB/haybarn/vgi-lint `ATTACH` — it
`exec uv run --project <repo> --quiet vgi-etf-schwab-worker`, resolving the project env
(`vgi-python` + `curl_cffi` + `pyarrow`) and running the console script (`[project.scripts]`
→ `vgi_etf_schwab.worker:main` → `SchwabWorker().run()`). uv's diagnostics go to stderr, so stdout
stays a clean Arrow IPC stream. No network happens at import (schema derivation is bind-only).

## Commands

```bash
uv sync --extra dev   # install (vgi-python from ../vgi-python via tool.uv.sources; curl_cffi + pyarrow)
uv run pytest -q      # unit tests: SDK-free driver + Arrow batch builders (injected fakes, no network)
uv run ruff check . && uv run ruff format --check . && uv run mypy vgi_etf_schwab/
./run_tests.sh        # haybarn SQLLogic E2E: worker under real DuckDB + community vgi ext (hits Schwab live)
uvx --prerelease allow --from vgi-lint-check vgi-lint bin/vgi-etf-schwab-worker --fail-on info --no-execute
```

`run_tests.sh` sets `VGI_TEST_WORKER=bin/vgi-etf-schwab-worker` + `VGI_WORKER_CATALOG_NAME=schwab`
and runs `test/sql/*.test` (DESCRIBE schema asserts, bind-only → deterministic; plus a few
live-invariant asserts that hit Schwab — fine for an egress connector). CI runs pytest/mypy/ruff,
this haybarn suite, and the vgi-lint gate at `--fail-on info` (currently 100/100).

## Gotchas / conventions

- The framework's function classes are CLASSMETHOD-based, so the injected `get` is captured via a
  factory closure (`make_products_scan(get)` / `make_holdings_scan(get)`), not an instance field.
- Emit the holdings batch with `schema=cls.FIXED_SCHEMA` (NOT the projected `output_schema`) so
  `fund_ticker` is always present for partition-value auto-extraction (the `partition_columns.py`
  fixture pattern). Products emits with `params.output_schema` (projection-safe via `from_pydict`).
- `pa.schema([...])` over a heterogeneous `Field[T]` list trips a pyarrow-stubs quirk (mypy sees
  `list[object]`); annotate that one call `# type: ignore[arg-type]` (vgi-python does the same).
- vgi-lint rules that must stay satisfied: descriptions must NOT enumerate the worker's own
  functions (VGI173); arg docs must NOT restate the type (VGI313 — `holdings_scan`'s single
  `fund_ticker` arg is documented as an open ETF-ticker vocabulary, not the type); every function
  needs an agent test task (VGI520 — products/holdings/holdings_scan covered in `catalog.py`
  `vgi.agent_test_tasks`). `vgi-lint.toml` carries NO rule `ignore` list — VGI311/807/809 are
  satisfied by real design (optional arg + composite PK), not suppression. The only
  `[tool.vgi-lint-check.execution]` override widens the timeout (Akamai/pagination latency); it
  hides no finding.
- Don't add a secret type; this worker is keyless by design.
