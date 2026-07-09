"""Unit tests for the products / universe parsing paths (network-free, injected fake)."""

from __future__ import annotations

from datetime import date

from vgi_etf_schwab import schwab

from .fake_schwab import (
    SCHD_FUND,
    SCHF_FUND,
    FakeSchwab,
    full_router,
    non_fund_html,
    product_html,
    sitemap_xml,
)


def test_parse_universe_keeps_only_four_char_fund_slugs() -> None:
    xml = sitemap_xml(["SCHD", "schf"])
    uni = schwab.parse_universe(xml)
    assert uni == ["SCHD", "SCHF"]  # upper-cased, sorted; swppx/etfs/long slug dropped


def test_fetch_products_parses_facts_and_drops_non_funds() -> None:
    def route(url: str) -> str:
        if url == schwab.SITEMAP_URL:
            return sitemap_xml(["SCHD", "SCHF"])
        if url == schwab.product_page_url("SCHD"):
            return product_html(SCHD_FUND)
        if url == schwab.product_page_url("SCHF"):
            return non_fund_html("schf")  # not an ETF page -> dropped
        raise RuntimeError(url)

    fake = FakeSchwab(route)
    rows = schwab.fetch_products(fake.get)
    assert [r.ticker for r in rows] == ["SCHD"]
    p = rows[0]
    assert p.fund_name == "Schwab U.S. Dividend Equity ETF"
    assert p.cusip == "808524797"
    assert p.exchange == "NYSE Arca, Inc."
    assert p.index_name == "Dow Jones U.S. Dividend 100 Index"
    assert p.morningstar_category == "Large Value"
    assert p.management_style == "Passive"
    assert p.expense_ratio_percent == 0.06
    assert p.portfolio_turnover_percent == 41.96
    assert p.net_assets == 98169629916.13
    assert p.nav == 32.33
    assert p.shares_outstanding == 3036900000
    assert p.num_holdings == 103
    assert p.inception_date == date(2011, 10, 20)
    assert p.as_of_date == date(2026, 7, 8)


def test_fetch_products_narrows_to_one_ticker() -> None:
    fake = FakeSchwab(full_router({"SCHD": SCHD_FUND, "SCHF": SCHF_FUND}, {}))
    rows = schwab.fetch_products(fake.get, "schd")
    assert [r.ticker for r in rows] == ["SCHD"]
    # Only the sitemap and the one product page were fetched (not SCHF's).
    assert schwab.product_page_url("SCHF") not in fake.calls


def test_resolve_fund_matches_universe_case_insensitively() -> None:
    fake = FakeSchwab(full_router({"SCHD": SCHD_FUND}, {}))
    assert schwab.resolve_fund(fake.get, "schd") == "SCHD"
    assert schwab.resolve_fund(fake.get, "NOPE") is None
    assert schwab.resolve_fund(fake.get, "") is None
