"""Unit tests for the holdings parsing + pagination paths (network-free, injected fake)."""

from __future__ import annotations

from datetime import date

import pytest

from vgi_etf_schwab import schwab

from .fake_schwab import (
    SCHD_FUND,
    SCHF_FUND,
    SCHF_HOLDINGS,
    FakeHolding,
    FakeSchwab,
    full_router,
    holdings_html,
)


def test_parse_holdings_page_reads_asof_total_and_typed_cells() -> None:
    rows = [
        FakeHolding("UNITEDHEALTH GROUP INC", "91324P102", "UNH", "10,339,786", "4.49%", "$4.4B"),
        FakeHolding("US DOLLAR", "", "", "12,345.67", "0.10%", "$98.1M"),
    ]
    page = schwab.parse_holdings_page(holdings_html("SCHD", rows, as_of="07/08/26", total=103), "SCHD")
    assert page.as_of == date(2026, 7, 8)
    assert page.total == 103
    assert len(page.rows) == 2
    top = page.rows[0]
    assert top.fund_ticker == "SCHD"
    assert top.name == "UNITEDHEALTH GROUP INC"
    assert top.ticker == "UNH"
    assert top.cusip == "91324P102"
    assert top.weight_percent == 4.49
    assert top.quantity == 10339786
    assert top.market_value == 4_400_000_000.0
    cash = page.rows[1]
    assert cash.ticker is None  # blank symbol -> None
    assert cash.cusip is None
    assert cash.market_value == 98_100_000.0


def test_fetch_holdings_paginates_and_sorts_weight_desc() -> None:
    fake = FakeSchwab(full_router({"SCHD": SCHD_FUND}, {}))
    rows = schwab.fetch_holdings(fake.get, "SCHD")
    # page 0 (UNH, MRK) + page 1 (US DOLLAR) = 3 rows, weight-descending
    assert [r.ticker for r in rows] == ["UNH", "MRK", None]
    assert [r.weight_percent for r in rows] == [4.49, 4.37, 0.10]
    # both pager pages were fetched
    assert schwab.holdings_url("SCHD", 0) in fake.calls
    assert schwab.holdings_url("SCHD", 1) in fake.calls


def test_fetch_holdings_single_page_fund() -> None:
    fake = FakeSchwab(full_router({"SCHF": SCHF_FUND}, {"SCHF": SCHF_HOLDINGS}))
    rows = schwab.fetch_holdings(fake.get, "SCHF")
    assert [r.name for r in rows] == ["NESTLE SA", "ASML HOLDING NV"]
    assert schwab.holdings_url("SCHF", 1) not in fake.calls  # only one page


def test_fetch_holdings_propagates_page0_transport_error() -> None:
    def route(url: str) -> str:
        raise RuntimeError("schwab: HTTP 403")

    with pytest.raises(RuntimeError, match="403"):
        schwab.fetch_holdings(route, "SCHD")


def test_parse_holdings_page_no_table_returns_empty() -> None:
    page = schwab.parse_holdings_page("<html><body>nothing here</body></html>", "SCHD")
    assert page.rows == []


def test_page_count() -> None:
    assert schwab.page_count(None) == 1
    assert schwab.page_count(50) == 1
    assert schwab.page_count(100) == 1
    assert schwab.page_count(101) == 2
    assert schwab.page_count(1498) == 15
