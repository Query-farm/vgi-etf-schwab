"""The ``schwab`` declarative catalog + its ``vgi.*`` metadata tags (the channels vgi-lint grades).

Schwab Asset Management's public product / holdings pages are KEYLESS, so there is NO
secret type here. JSON-valued tags (keywords / categories / example_queries /
agent_test_tasks / executable_examples) are JSON strings; all example SQL is
catalog-qualified (``schwab.main.<obj>``) so it binds/runs when the catalog is attached.
"""

from __future__ import annotations

import json
from typing import Any

from vgi.catalog import Catalog, Schema, Table
from vgi.table_function import TableFunctionGenerator

from vgi_etf_schwab.schema import (
    HOLDINGS_SCHEMA,
    PRODUCTS_SCHEMA,
    result_columns_schema,
)

REPO = "https://github.com/Query-farm/vgi-etf-schwab"
ISSUES = f"{REPO}/issues"

# -- products -----------------------------------------------------------------------

PRODUCTS_COLUMN_COMMENTS: dict[str, str] = {
    "ticker": "Exchange ticker (e.g. SCHD).",
    "fund_name": "Full fund name as marketed, e.g. 'Schwab U.S. Dividend Equity ETF'.",
    "index_name": "Name of the index the fund tracks (e.g. 'Dow Jones U.S. Dividend 100 Index').",
    "morningstar_category": "Morningstar category (e.g. 'Large Value').",
    "management_style": "Management style — typically 'Passive' for Schwab's index ETFs.",
    "exchange": "Listing exchange (e.g. 'NYSE Arca, Inc.').",
    "cusip": "The fund's CUSIP identifier.",
    "inception_date": "Fund inception date.",
    "as_of_date": "As-of date for the point-in-time fields (net_assets, nav).",
    "net_assets": "Total net assets (fund AUM), in USD.",
    "nav": "Net asset value per share, in USD.",
    "expense_ratio_percent": "Total (net) expense ratio, in percent points (0.06 = 0.06%).",
    "portfolio_turnover_percent": "Annual portfolio turnover rate, in percent points.",
    "shares_outstanding": "Count of fund shares currently in issue (as of as_of_date).",
    "num_holdings": "Number of holdings in the fund.",
}

PRODUCTS_TABLE_TAGS: dict[str, str] = {
    "vgi.category": "catalog",
    "domain": "finance",
    "vgi.keywords": json.dumps(
        ["ETF", "fund catalog", "product list", "expense ratio", "net assets", "index", "ticker"]
    ),
    "vgi.doc_llm": (
        "The Schwab Asset Management US ETF catalog as a plain table (query it directly, no "
        "arguments): one row per ETF with ticker, name, tracked index, Morningstar category, net "
        "assets, NAV, expense ratio, holdings count, and shares outstanding. Narrow it with a WHERE "
        "clause on ticker, morningstar_category, and so on. The expense_ratio_percent and "
        "portfolio_turnover_percent columns hold percent points (0.06 means 0.06%). Start here to "
        "find a fund's ticker for the holdings table."
    ),
    "vgi.doc_md": (
        "## products\n\n"
        "The Schwab US ETF catalog as a base table — one row per fund. It takes no arguments; query "
        "it directly and filter with a WHERE clause (e.g. `WHERE morningstar_category = 'Large Value' "
        "ORDER BY net_assets DESC`; see the example queries). Percent columns (`*_percent`) are in "
        "**percent points** (an expense ratio of 0.06 means 0.06%). The ticker column is the key for "
        "the holdings table."
    ),
    "vgi.example_queries": json.dumps(
        [
            {
                "description": "Ten largest Schwab ETFs by net assets",
                "sql": (
                    "SELECT ticker, fund_name, net_assets FROM schwab.main.products ORDER BY net_assets DESC LIMIT 10"
                ),
            },
            {
                "description": "Cheapest funds by expense ratio",
                "sql": (
                    "SELECT ticker, fund_name, expense_ratio_percent FROM schwab.main.products "
                    "ORDER BY expense_ratio_percent LIMIT 10"
                ),
            },
            {
                "description": "Look up a single fund by ticker",
                "sql": (
                    "SELECT ticker, fund_name, expense_ratio_percent FROM schwab.main.products WHERE ticker = 'SCHD'"
                ),
            },
        ]
    ),
    "vgi.result_columns_schema": result_columns_schema(PRODUCTS_SCHEMA, PRODUCTS_COLUMN_COMMENTS),
}

# -- holdings -----------------------------------------------------------------------

HOLDINGS_COLUMN_COMMENTS: dict[str, str] = {
    "fund_ticker": (
        "The fund's ticker (e.g. SCHD) — the hive partition key; constant for every row of a "
        "fund. Filter on it to pick funds; omit to stream all."
    ),
    "as_of_date": "Holdings as-of date (the published page's own date; current holdings only).",
    "weight_percent": "Percent of the fund's assets, in percent points (4.49 = 4.49%; weights sum to ~100).",
    "ticker": "Constituent ticker / symbol (blank for cash and derivative lines).",
    "name": "Constituent / issue name.",
    "cusip": "Constituent CUSIP identifier (empty string for cash / derivative lines that have none).",
    "quantity": "Number of shares / units / par held.",
    "market_value": (
        "Market value of the position, in USD. Schwab shows this abbreviated (e.g. '$4.4B'), so it is approximate."
    ),
}

HOLDINGS_TABLE_TAGS: dict[str, str] = {
    "vgi.category": "holdings",
    "domain": "finance",
    "vgi.keywords": json.dumps(["holdings", "constituents", "portfolio", "weights", "positions", "exposure"]),
    "vgi.doc_llm": (
        "Detailed portfolio holdings for Schwab ETFs as a hive-partitioned table. It is partitioned by "
        "fund_ticker (the FUND's ticker, distinct from the constituent `ticker` column): filter "
        "`WHERE fund_ticker = '…'` (or `fund_ticker IN (…)`) to pick funds, or scan with no filter to "
        "stream EVERY fund's holdings (~35 funds — slow, and a broad bond fund can list thousands of "
        "constituents, so prefer a filter). Schwab publishes CURRENT holdings only, so there is no "
        "historical as-of date; as_of_date is the published page's own date. Rows come back "
        "weight-descending; weight_percent is in percent points (4.49 = 4.49%). market_value is "
        "abbreviated on the page so it is approximate. Join on fund_ticker to products.ticker for "
        "fund-level facts."
    ),
    "vgi.doc_md": (
        "## holdings\n\n"
        "Detailed fund holdings as a **hive-partitioned table**, partitioned by `fund_ticker` (the "
        "fund's ticker). `fund_ticker` is distinct from `ticker` (the constituent's own symbol). "
        "Filter `WHERE fund_ticker = 'SCHD'` for one fund's holdings (see the example queries).\n\n"
        "`WHERE fund_ticker IN ('SCHD','SCHF')` fans out per partition; an unfiltered scan streams "
        "every fund (~35 partitions — slow). Schwab publishes **current holdings only** (no historical "
        "dates). `weight_percent` is in percent points (4.49 = 4.49%); `market_value` is approximate "
        "(abbreviated on the page)."
    ),
    "vgi.result_columns_schema": result_columns_schema(HOLDINGS_SCHEMA, HOLDINGS_COLUMN_COMMENTS),
    "vgi.example_queries": json.dumps(
        [
            {
                "description": "Top 10 current holdings of SCHD",
                "sql": (
                    "SELECT name, ticker, weight_percent FROM schwab.main.holdings "
                    "WHERE fund_ticker = 'SCHD' ORDER BY weight_percent DESC LIMIT 10"
                ),
            },
            {
                "description": "The largest positions of the International Equity ETF",
                "sql": (
                    "SELECT name, weight_percent, market_value FROM schwab.main.holdings "
                    "WHERE fund_ticker = 'SCHF' ORDER BY weight_percent DESC LIMIT 10"
                ),
            },
            {
                "description": "Two funds at once (partition fan-out)",
                "sql": (
                    "SELECT fund_ticker, name, weight_percent FROM schwab.main.holdings "
                    "WHERE fund_ticker IN ('SCHD', 'SCHF')"
                ),
            },
        ]
    ),
}

# -- catalog ------------------------------------------------------------------------

CATALOG_TAGS: dict[str, str] = {
    "vgi.title": "Schwab Asset Management ETFs",
    "vgi.doc_llm": (
        "Schwab Asset Management US ETF data as SQL tables. Reach for it to screen the Schwab ETF "
        "lineup on key facts (net assets, expense ratio, tracked index, category), and to inspect "
        "what a fund currently holds. The central concept is the fund, identified by its exchange "
        "ticker (e.g. SCHD); start from the catalog to find that key, then drill into a specific "
        "fund's holdings. Data is Schwab's public fund website: best-effort, for informational use."
    ),
    "vgi.doc_md": (
        "## Schwab Asset Management ETFs\n\n"
        "Schwab Asset Management US ETF data, exposed as DuckDB tables.\n\n"
        "The **fund** is the unit of the data and is keyed by an exchange `ticker` (e.g. `SCHD`) — "
        "begin at the catalog to discover that key, then drill into a fund's holdings. Holdings are "
        "the current published portfolio (Schwab does not publish historical holdings).\n\n"
        "Data is provided for informational use; review Schwab's terms before redistribution."
    ),
    "vgi.keywords": json.dumps(
        [
            "ETF",
            "Schwab",
            "Schwab Asset Management",
            "holdings",
            "portfolio",
            "fund",
            "index fund",
            "expense ratio",
            "low cost",
        ]
    ),
    "vgi.author": "Query Farm LLC",
    "vgi.copyright": "Copyright 2026 Query Farm LLC",
    "vgi.license": "MIT",
    "vgi.support_contact": ISSUES,
    "vgi.support_policy_url": ISSUES,
    # At least one guaranteed-runnable example at the catalog level (VGI509). No
    # expected_result — Schwab data is live/non-deterministic.
    "vgi.executable_examples": json.dumps(
        [
            {
                "name": "largest_etfs",
                "description": "The largest Schwab ETFs by net assets",
                "sql": (
                    "SELECT ticker, fund_name, net_assets FROM schwab.main.products ORDER BY net_assets DESC LIMIT 5"
                ),
            },
            {
                "name": "top_holdings",
                "description": "The top holdings of the Schwab U.S. Dividend Equity ETF",
                "sql": (
                    "SELECT name, ticker, weight_percent FROM schwab.main.holdings "
                    "WHERE fund_ticker = 'SCHD' ORDER BY weight_percent DESC LIMIT 5"
                ),
            },
        ]
    ),
    # Agent-suitability suite (catalog only). Each task carries a deterministic check_sql;
    # reference_sql is deliberately omitted (live data). One task per callable surface
    # (products, holdings, holdings_scan) satisfies VGI520.
    "vgi.agent_test_tasks": json.dumps(
        [
            {
                "name": "schd_exists",
                "prompt": "Does Schwab offer an ETF with the ticker SCHD, and what is it called?",
                "check_sql": "SELECT count(*) > 0 FROM schwab.main.products WHERE ticker = 'SCHD'",
                "success_criteria": (
                    "The answer confirms SCHD is the Schwab U.S. Dividend Equity ETF, found via the products table."
                ),
            },
            {
                "name": "schd_expense_ratio",
                "prompt": "What is the expense ratio of the Schwab U.S. Dividend Equity ETF (SCHD)?",
                "check_sql": (
                    "SELECT count(*) > 0 FROM schwab.main.products WHERE ticker = 'SCHD' "
                    "AND expense_ratio_percent IS NOT NULL"
                ),
                "success_criteria": (
                    "The answer reports SCHD's expense ratio (a small percentage) from the products table."
                ),
            },
            {
                "name": "schd_top_holding",
                "prompt": (
                    "What is the single largest holding of the Schwab U.S. Dividend Equity ETF (SCHD) right now?"
                ),
                "check_sql": "SELECT count(*) > 0 FROM schwab.main.holdings WHERE fund_ticker = 'SCHD'",
                "success_criteria": (
                    "The answer names SCHD's top holding by weight, obtained from the holdings table."
                ),
            },
            {
                "name": "schd_holdings_scan",
                "prompt": (
                    "Using the holdings backing scan with the fund ticker passed as its argument, "
                    "list a few SCHD constituents by weight."
                ),
                "check_sql": ("SELECT count(*) > 0 FROM schwab.main.holdings_scan(fund_ticker => 'SCHD')"),
                "success_criteria": ("The answer returns SCHD constituents via holdings_scan(fund_ticker => 'SCHD')."),
            },
        ]
    ),
}

SCHEMA_TAGS: dict[str, str] = {
    "vgi.title": "Schwab Fund Data",
    "vgi.doc_llm": (
        "Schwab Asset Management ETF data at two levels. At the catalog level you screen the whole "
        "lineup on key facts and resolve a fund's key. At the fund level you drill into one fund's "
        "current holdings. A fund is keyed by its exchange `ticker` (e.g. `SCHD`); resolve the key at "
        "the catalog level first."
    ),
    "vgi.doc_md": (
        "## Schwab fund data\n\n"
        "Work happens at two levels. **Catalog level:** screen the lineup on key facts and find a "
        "fund's key. **Fund level:** drill into a single fund's constituents. A fund is keyed by its "
        "exchange `ticker` (e.g. `SCHD`).\n\n"
        "Holdings are the current published portfolio; Schwab does not publish historical holdings."
    ),
    "vgi.keywords": json.dumps(["ETF holdings", "fund catalog", "portfolio", "Schwab", "index fund"]),
    "domain": "finance",
    "vgi.categories": json.dumps(
        [
            {"name": "catalog", "title": "Fund Catalog", "description": "The ETF product list and per-fund key facts."},
            {"name": "holdings", "title": "Holdings", "description": "Detailed current portfolio holdings."},
        ]
    ),
    "vgi.example_queries": json.dumps(
        [
            {
                "description": "Ten largest Schwab ETFs by net assets",
                "sql": (
                    "SELECT ticker, fund_name, net_assets FROM schwab.main.products ORDER BY net_assets DESC LIMIT 10"
                ),
            },
            {
                "description": "Top holdings of SCHD",
                "sql": (
                    "SELECT name, ticker, weight_percent FROM schwab.main.holdings "
                    "WHERE fund_ticker = 'SCHD' ORDER BY weight_percent DESC LIMIT 10"
                ),
            },
        ]
    ),
}


def make_catalog(
    products_scan: type[TableFunctionGenerator[Any, Any]],
    holdings_scan: type[TableFunctionGenerator[Any, Any]],
) -> Catalog:
    """Build the ``schwab`` catalog descriptor.

    ``products`` and ``holdings`` are base TABLES backed by scan functions. The products
    scan is registered for dispatch (via ``Table.function``) but NOT listed as a callable
    function. The holdings scan is BOTH the table backing AND listed in ``Schema.functions``
    so the DuckDB extension can discover its ``filter_pushdown`` capability and push the
    ``fund_ticker`` partition filter into the table scan.

    Args:
        products_scan: The zero-arg scan backing the ``products`` base table.
        holdings_scan: The pushdown scan backing the ``holdings`` base table.

    Returns:
        The declarative :class:`~vgi.catalog.Catalog`.
    """
    return Catalog(
        name="schwab",
        default_schema="main",
        comment=(
            "Schwab Asset Management US ETF data as DuckDB tables: products (catalog) & holdings "
            "(ticker-partitioned, current holdings) — vgi-etf-schwab"
        ),
        source_url=REPO,
        tags=CATALOG_TAGS,
        schemas=[
            Schema(
                name="main",
                comment="Schwab fund data: the ETF catalog and detailed current holdings.",
                tags=SCHEMA_TAGS,
                # holdings_scan is LISTED so the extension can push fund_ticker into the table.
                functions=[holdings_scan],
                tables=[
                    Table(
                        name="products",
                        function=products_scan,
                        # Each fund is keyed by its exchange ticker (advisory — not enforced on scan).
                        primary_key=(("ticker",),),
                        # The Schwab US ETF lineup is ~35 funds; headroom to ~80.
                        cardinality_estimate=35,
                        cardinality_max=80,
                        comment=(
                            "Every Schwab US ETF with its key facts, one row per fund. Query directly (no "
                            "arguments) and filter with WHERE; percent columns are in percent points."
                        ),
                        column_comments=PRODUCTS_COLUMN_COMMENTS,
                        tags=PRODUCTS_TABLE_TAGS,
                    ),
                    Table(
                        name="holdings",
                        function=holdings_scan,
                        # fund_ticker is always populated (the scan tags every row with its fund);
                        # cusip is emitted as "" (never NULL) for cash / derivative lines, so
                        # (fund_ticker, cusip) is a NOT NULL composite key identifying each
                        # constituent within a fund (advisory — not enforced on a live scan).
                        not_null=("fund_ticker", "cusip"),
                        primary_key=(("fund_ticker", "cusip"),),
                        # Whole-table estimate: ~35 funds; a broad bond fund alone can list 10k+
                        # constituents. Schwab publishes current holdings only, so there is NO time travel.
                        cardinality_estimate=40000,
                        cardinality_max=400000,
                        comment=(
                            "Detailed current fund holdings, hive-partitioned by fund_ticker (filter WHERE "
                            "fund_ticker = … for one fund, or scan unfiltered for all). Schwab publishes current "
                            "holdings only (no historical dates)."
                        ),
                        column_comments=HOLDINGS_COLUMN_COMMENTS,
                        tags=HOLDINGS_TABLE_TAGS,
                    ),
                ],
            ),
        ],
    )
