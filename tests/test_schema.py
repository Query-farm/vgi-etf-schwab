"""Unit tests for the Arrow schema + batch builders and the client injection/caching."""

from __future__ import annotations

import json
from datetime import date

import pyarrow as pa

from vgi_etf_schwab import schema
from vgi_etf_schwab.client import make_schwab_get
from vgi_etf_schwab.schwab import SITEMAP_URL, HoldingRow, ProductRow


def test_products_batch_has_typed_columns() -> None:
    row = ProductRow(
        ticker="SCHD",
        fund_name="Schwab U.S. Dividend Equity ETF",
        exchange="NYSE Arca, Inc.",
        cusip="808524797",
        index_name="Dow Jones U.S. Dividend 100 Index",
        morningstar_category="Large Value",
        management_style="Passive",
        inception_date=date(2011, 10, 20),
        as_of_date=date(2026, 7, 8),
        net_assets=98169629916.13,
        nav=32.33,
        expense_ratio_percent=0.06,
        portfolio_turnover_percent=41.96,
        shares_outstanding=3036900000.0,
        num_holdings=103.0,
    )
    batch = pa.RecordBatch.from_pydict(schema.products_columns([row]), schema=schema.PRODUCTS_SCHEMA)
    assert batch.num_rows == 1
    assert batch.schema.field("inception_date").type == pa.date32()
    assert batch.schema.field("shares_outstanding").type == pa.int64()
    assert batch.schema.field("net_assets").type == pa.float64()
    d = batch.to_pylist()[0]
    assert d["inception_date"] == date(2011, 10, 20)
    assert d["shares_outstanding"] == 3036900000
    assert d["expense_ratio_percent"] == 0.06


def test_holdings_batch_partition_field_and_types() -> None:
    row = HoldingRow(
        fund_ticker="SCHD",
        as_of_date=date(2026, 7, 8),
        weight_percent=4.49,
        ticker="UNH",
        name="UNITEDHEALTH GROUP INC",
        cusip="91324P102",
        quantity=10339786.0,
        market_value=4_400_000_000.0,
    )
    batch = pa.RecordBatch.from_pydict(schema.holdings_columns([row]), schema=schema.HOLDINGS_SCHEMA)
    assert batch.to_pylist()[0]["fund_ticker"] == "SCHD"
    # fund_ticker carries the VGI partition-column marker.
    md = schema.HOLDINGS_SCHEMA.field("fund_ticker").metadata or {}
    assert md.get(b"vgi.partition_column") == b"true"


def test_result_columns_schema_json_shape() -> None:
    js = json.loads(schema.result_columns_schema(schema.PRODUCTS_SCHEMA, {"ticker": "the ticker"}))
    by_name = {c["name"]: c for c in js}
    assert by_name["ticker"] == {"name": "ticker", "type": "VARCHAR", "description": "the ticker"}
    assert by_name["net_assets"]["type"] == "DOUBLE"
    assert by_name["inception_date"]["type"] == "DATE"
    assert by_name["num_holdings"]["type"] == "BIGINT"


def test_client_caches_sitemap_only() -> None:
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return "body"

    get = make_schwab_get(fetch, catalog_cache_seconds=1000, now=lambda: 0.0)
    get(SITEMAP_URL)
    get(SITEMAP_URL)  # served from cache
    assert calls.count(SITEMAP_URL) == 1
    get("https://www.schwabassetmanagement.com/products/schd")
    get("https://www.schwabassetmanagement.com/products/schd")  # product pages never cached
    assert calls.count("https://www.schwabassetmanagement.com/products/schd") == 2
