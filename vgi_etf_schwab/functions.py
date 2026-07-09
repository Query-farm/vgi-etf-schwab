"""The VGI table-function generators backing the ``products`` and ``holdings`` base tables.

Both are built by factories that close over an injected ``get(url) -> str`` transport, so
the worker wires the real ``curl_cffi`` client and the unit tests wire a fake (mirroring
how the pure driver is injected). All keyless.

* ``products_scan`` — a zero-arg, streaming, queue-backed scan of the Schwab US ETF lineup.
  ``on_init`` seeds a BoundStorage queue with the sitemap universe; ``process`` pops one
  ticker per tick, fetches that fund's product page, and emits its row — so the first row is
  prompt and ``max_workers`` parallel workers fan out the per-fund fetches. It backs the
  ``products`` table (registered for scan dispatch, but NOT listed as a callable function —
  users query the table).
* ``holdings_scan`` — a streaming, queue-backed, HIVE-PARTITIONED scan (one
  SINGLE_VALUE partition per fund, keyed on ``fund_ticker``). ``on_init`` reads the
  pushed ``fund_ticker`` filter — or, absent one, the entire ETF universe from the
  sitemap — and seeds a :class:`~vgi.function_storage.BoundStorage` work queue with one
  item per fund; ``process`` pops one fund per tick, fetches its holdings, and emits a
  single partition batch. ``filter_pushdown`` + being LISTED is what lets DuckDB push the
  ``fund_ticker`` filter into the scan. Schwab publishes CURRENT holdings only, so there
  is NO time travel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pyarrow as pa
from vgi.invocation import GlobalInitResponse
from vgi.metadata import FunctionExample, PartitionKind
from vgi.table_function import (
    InitParams,
    ProcessParams,
    TableFunctionGenerator,
    bind_fixed_schema,
)
from vgi_rpc.rpc import OutputCollector

from vgi_etf_schwab.client import Getter
from vgi_etf_schwab.schema import (
    HOLDINGS_SCHEMA,
    PRODUCTS_SCHEMA,
    holdings_columns,
    products_columns,
    result_columns_schema,
)
from vgi_etf_schwab.schwab import (
    fetch_holdings,
    fetch_universe,
    parse_product,
    product_page_url,
)

#: Fan-out cap for the parallel holdings scan. Kept modest to stay gentle on Akamai
#: (a burst of parallel requests can draw a 403). A single-fund filter has one queue
#: item, so it runs on one worker regardless.
HOLDINGS_MAX_WORKERS = 4

#: Fan-out cap for the parallel products scan (per-fund product-page fetches).
PRODUCTS_MAX_WORKERS = 8


@dataclass(frozen=True, slots=True)
class _EmptyArgs:
    """No arguments — ``products`` and ``holdings`` are zero-arg base tables."""


# -- holdings_scan metadata (vgi.* doc/discovery channels vgi-lint grades) ---------

_HOLDINGS_SCAN_DESCS = {
    "fund_ticker": "The fund's ticker — the partition filter.",
    "as_of_date": "The holdings as-of date (the published page's own date).",
    "weight_percent": "Percent of the fund's assets, in percent points (4.49 = 4.49%).",
    "ticker": "Constituent ticker / symbol (blank for cash and derivative lines).",
    "name": "Constituent / issue name.",
    "cusip": "Constituent CUSIP.",
    "quantity": "Number of shares / units / par held.",
    "market_value": "Market value of the position, in USD (abbreviated on the page, so approximate).",
}

_HOLDINGS_SCAN_TAGS = {
    "vgi.category": "holdings",
    "vgi.doc_llm": (
        "The backing scan for the `holdings` table. Prefer querying the `holdings` table. "
        "Hive-partitioned by fund_ticker (the fund's ticker, distinct from the constituent "
        "`ticker` column): filter WHERE fund_ticker = '…' (or fund_ticker IN (…)) for specific "
        "funds, or scan with no filter to stream every fund (~35 partitions — slow). "
        "weight_percent is in percent points (4.49 = 4.49%). Schwab publishes current holdings "
        "only, so there is no historical as-of date."
    ),
    "vgi.doc_md": (
        "## holdings_scan\n\n"
        "The backing scan for the **`holdings` table** — prefer the table. Hive-partitioned by "
        "`fund_ticker`: filter `WHERE fund_ticker = 'SCHD'` for one fund, or scan with no filter "
        "to stream every fund (see the example queries). `fund_ticker` is distinct from the "
        "constituent `ticker` column."
    ),
    "vgi.result_columns_schema": result_columns_schema(HOLDINGS_SCHEMA, _HOLDINGS_SCAN_DESCS),
}


def make_products_scan(get: Getter) -> type[TableFunctionGenerator[_EmptyArgs, None]]:
    """Build the streaming, queue-backed scan behind the ``products`` base table.

    Mirrors the holdings scan: ``on_init`` seeds a BoundStorage work queue with the sitemap
    universe (one item per candidate ticker); ``process`` pops one ticker per tick, fetches
    that fund's product page, and emits its row. So the FIRST row is emitted promptly (no
    fetch-everything-then-emit stall — an agent's ``LIMIT``/cancel works), and ``max_workers``
    parallel workers fan out the per-fund page fetches (the whole ~35-page catalog is drained
    concurrently instead of serially). A non-ETF slug (no fund-facts table) or a failed fetch
    is skipped, never fatal.
    """

    @bind_fixed_schema
    class ProductsScan(TableFunctionGenerator[_EmptyArgs, None]):
        """Schwab US ETF catalog — the streaming backing scan for the ``products`` table."""

        FIXED_SCHEMA: ClassVar[pa.Schema] = PRODUCTS_SCHEMA

        class Meta:
            """Function metadata: parallel per-fund fan-out over the sitemap universe."""

            name = "products_scan"
            description = "Schwab US ETF catalog — backing scan for the products table."
            max_workers = PRODUCTS_MAX_WORKERS

        @classmethod
        def on_init(cls, params: InitParams[_EmptyArgs]) -> GlobalInitResponse:
            """Seed the work queue with the candidate ETF universe from the sitemap."""
            params.storage.queue_push([t.encode("utf-8") for t in fetch_universe(get)])
            return GlobalInitResponse(max_workers=PRODUCTS_MAX_WORKERS)

        @classmethod
        def process(cls, params: ProcessParams[_EmptyArgs], state: None, out: OutputCollector) -> None:
            """Pop one ticker per tick, emit that fund's row; skip non-ETF slugs / failed fetches."""
            while True:
                item = params.storage.queue_pop()
                if item is None:
                    out.finish()
                    return
                ticker = item.decode("utf-8")
                try:
                    row = parse_product(str(get(product_page_url(ticker))), ticker)
                except Exception:
                    row = None
                if row is None or row.cusip is None:
                    continue  # a non-ETF slug (no fund-facts table) or a failed fetch
                out.emit(pa.RecordBatch.from_pydict(products_columns([row]), schema=cls.FIXED_SCHEMA))
                return

    return ProductsScan


def make_holdings_scan(get: Getter) -> type[TableFunctionGenerator[_EmptyArgs, None]]:
    """Build the hive-partitioned, queue-backed scan backing the ``holdings`` table."""

    @bind_fixed_schema
    class HoldingsScan(TableFunctionGenerator[_EmptyArgs, None]):
        """Detailed fund holdings, hive-partitioned by ``fund_ticker`` (one partition per fund).

        Prefer querying the ``holdings`` table. Filter ``WHERE fund_ticker = 'SCHD'`` (or
        ``fund_ticker IN (…)``) for specific funds, or scan with no filter to stream every
        fund's holdings. ``weight_percent`` is in percent points; Schwab publishes current
        holdings only.
        """

        FIXED_SCHEMA: ClassVar[pa.Schema] = HOLDINGS_SCHEMA

        class Meta:
            """Function metadata: filter pushdown + SINGLE_VALUE partitioning on ``fund_ticker``."""

            name = "holdings_scan"
            description = (
                "Backing scan for the holdings table — prefer the `holdings` table. Detailed fund "
                "holdings, hive-partitioned by fund_ticker: filter WHERE fund_ticker = 'SCHD' (or "
                "fund_ticker IN (…)) for specific funds, or scan with no filter to stream every "
                "fund's holdings. weight_percent is in percent points; Schwab publishes current "
                "holdings only."
            )
            categories = ["holdings"]
            filter_pushdown = True
            partition_kind = PartitionKind.SINGLE_VALUE_PARTITIONS
            max_workers = HOLDINGS_MAX_WORKERS
            examples = [
                FunctionExample(
                    sql=(
                        "SELECT name, weight_percent FROM schwab.main.holdings_scan() "
                        "WHERE fund_ticker = 'SCHD' ORDER BY weight_percent DESC LIMIT 10"
                    ),
                    description="Top 10 holdings of SCHD via the backing scan",
                ),
                FunctionExample(
                    sql=(
                        "SELECT fund_ticker, count(*) FROM schwab.main.holdings_scan() "
                        "WHERE fund_ticker IN ('SCHD', 'SCHF') GROUP BY fund_ticker"
                    ),
                    description="Two partitions at once (fan-out)",
                ),
            ]
            tags = _HOLDINGS_SCAN_TAGS

        @classmethod
        def on_init(cls, params: InitParams[_EmptyArgs]) -> GlobalInitResponse:
            """Seed the work queue with the target funds: the pushed filter, else the whole universe."""
            pf = params.init_call.pushdown_filters
            jk = params.init_call.join_keys
            filters = cls.pushdown_filters(pf, join_keys=jk) if pf is not None else None
            requested: list[str] = []
            if filters is not None:
                values = filters.get_column_values("fund_ticker")
                if values is not None:
                    requested = [str(v).upper() for v in values.to_pylist() if v is not None]
            # De-dup (order-preserving) when a filter was pushed; else the whole universe.
            targets = list(dict.fromkeys(requested)) if requested else fetch_universe(get)
            params.storage.queue_push([t.encode("utf-8") for t in targets])
            return GlobalInitResponse(max_workers=HOLDINGS_MAX_WORKERS)

        @classmethod
        def process(cls, params: ProcessParams[_EmptyArgs], state: None, out: OutputCollector) -> None:
            """Pop one fund per tick, emit its holdings as a single partition; skip empty funds."""
            while True:
                item = params.storage.queue_pop()
                if item is None:
                    out.finish()
                    return
                ticker = item.decode("utf-8")
                rows = fetch_holdings(get, ticker)
                if not rows:
                    continue
                out.emit(pa.RecordBatch.from_pydict(holdings_columns(rows), schema=cls.FIXED_SCHEMA))
                return

    return HoldingsScan
