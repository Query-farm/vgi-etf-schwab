"""Arrow output schemas + row -> batch mapping for the products / holdings surfaces.

Schwab fund data has a STABLE, known shape, so we emit real typed columns (not a single
JSON string): ``string`` identifiers/names, ``float64`` prices/weights/ratios, ``int64``
counts, and a real Arrow DATE (``date32``) for every calendar date. Percent-valued
columns carry a ``_percent`` suffix and hold percent-magnitude numbers (e.g. ``0.06``
means 0.06%); the driver passes Schwab's already-percent figures straight through.
Non-percent ratios are NOT suffixed (there are none here).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

import pyarrow as pa
from vgi.schema_utils import partition_field

from vgi_etf_schwab.schwab import HoldingRow, ProductRow


def _duckdb_type(dtype: pa.DataType) -> str:
    """Map an Arrow field type to the DuckDB type name shown in docs."""
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype):
        return "VARCHAR"
    if pa.types.is_floating(dtype):
        return "DOUBLE"
    if pa.types.is_integer(dtype):
        return "BIGINT"
    if pa.types.is_date(dtype):
        return "DATE"
    return "VARCHAR"


def result_columns_schema(schema: pa.Schema, descriptions: Mapping[str, str]) -> str:
    """Build the ``vgi.result_columns_schema`` tag value from an Arrow schema + descriptions.

    A JSON array of ``{name, type, description}``, DRY from the Arrow schema and a
    name -> description map.
    """
    return json.dumps(
        [
            {
                "name": field.name,
                "type": _duckdb_type(field.type),
                "description": descriptions.get(field.name, field.name),
            }
            for field in schema
        ]
    )


def _big_or_none(n: float | None) -> int | None:
    """Return an int (rounded) for an int64 cell, or ``None``."""
    return None if n is None else round(n)


# -- products ---------------------------------------------------------------------

PRODUCTS_SCHEMA: pa.Schema = pa.schema(
    [  # type: ignore[arg-type]  # pyarrow stubs: heterogeneous Field[T] list joins to object
        pa.field("ticker", pa.string()),
        pa.field("fund_name", pa.string()),
        pa.field("index_name", pa.string()),
        pa.field("morningstar_category", pa.string()),
        pa.field("management_style", pa.string()),
        pa.field("exchange", pa.string()),
        pa.field("cusip", pa.string()),
        pa.field("inception_date", pa.date32()),
        pa.field("as_of_date", pa.date32()),
        pa.field("net_assets", pa.float64()),
        pa.field("nav", pa.float64()),
        pa.field("expense_ratio_percent", pa.float64()),
        pa.field("portfolio_turnover_percent", pa.float64()),
        pa.field("shares_outstanding", pa.int64()),
        pa.field("num_holdings", pa.int64()),
    ]
)


def products_columns(rows: Iterable[ProductRow]) -> dict[str, list[Any]]:
    """Build a column-name -> values dict for the products batch."""
    rows = list(rows)
    return {
        "ticker": [r.ticker for r in rows],
        "fund_name": [r.fund_name for r in rows],
        "index_name": [r.index_name for r in rows],
        "morningstar_category": [r.morningstar_category for r in rows],
        "management_style": [r.management_style for r in rows],
        "exchange": [r.exchange for r in rows],
        "cusip": [r.cusip for r in rows],
        "inception_date": [r.inception_date for r in rows],
        "as_of_date": [r.as_of_date for r in rows],
        "net_assets": [r.net_assets for r in rows],
        "nav": [r.nav for r in rows],
        "expense_ratio_percent": [r.expense_ratio_percent for r in rows],
        "portfolio_turnover_percent": [r.portfolio_turnover_percent for r in rows],
        "shares_outstanding": [_big_or_none(r.shares_outstanding) for r in rows],
        "num_holdings": [_big_or_none(r.num_holdings) for r in rows],
    }


# -- holdings ---------------------------------------------------------------------

# fund_ticker is the hive partition key: the holdings scan emits one SINGLE_VALUE
# partition per fund.
HOLDINGS_SCHEMA: pa.Schema = pa.schema(
    [
        partition_field("fund_ticker", pa.string()),
        pa.field("as_of_date", pa.date32()),
        pa.field("weight_percent", pa.float64()),
        pa.field("ticker", pa.string()),
        pa.field("name", pa.string()),
        pa.field("cusip", pa.string()),
        pa.field("quantity", pa.float64()),
        pa.field("market_value", pa.float64()),
    ]
)


def holdings_columns(rows: Iterable[HoldingRow]) -> dict[str, list[Any]]:
    """Build a column-name -> values dict for the holdings batch."""
    rows = list(rows)
    return {
        "fund_ticker": [r.fund_ticker for r in rows],
        "as_of_date": [r.as_of_date for r in rows],
        "weight_percent": [r.weight_percent for r in rows],
        "ticker": [r.ticker for r in rows],
        "name": [r.name for r in rows],
        "cusip": [r.cusip for r in rows],
        "quantity": [r.quantity for r in rows],
        "market_value": [r.market_value for r in rows],
    }
