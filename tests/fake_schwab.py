"""A tiny in-process fake of the Schwab Asset Management endpoints.

Enough to prove the driver: it records every requested URL (so a test can assert the wire
contract) and returns canned HTML/XML shaped like the real sitemap, a per-fund product page
(a "fund facts" table), and a paginated all-holdings page. No network.

The driver takes ONE injected transport: ``get(url) -> str`` (text — HTML or XML).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vgi_etf_schwab.schwab import (
    SCHWAB_HOST,
    SITEMAP_URL,
    holdings_url,
    product_page_url,
)


class FakeSchwab:
    """Records requested URLs and routes them to canned responses."""

    def __init__(self, route: Callable[[str], str]) -> None:
        self.calls: list[str] = []
        self._route = route

    def get(self, url: str) -> str:
        self.calls.append(url)
        return self._route(url)


# -- sitemap.xml (the fund universe) ----------------------------------------------


def sitemap_xml(tickers: list[str]) -> str:
    """Build a sitemap urlset with the given ETF slugs plus decoy non-fund slugs."""

    def url(slug: str) -> str:
        return f"<url><loc>{SCHWAB_HOST}/products/{slug}</loc></url>"

    locs = (
        [url(t.lower()) for t in tickers]
        + [url("swppx")]  # a 5-letter mutual fund — must be filtered out
        + [url("etfs")]  # a section landing page — must be filtered out
        + [url("prospectus-and-reports-etf")]  # a long slug — ignored
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(locs) + "</urlset>"
    )


# -- per-fund product page (the fund-facts table) ---------------------------------


@dataclass(frozen=True)
class FakeFund:
    ticker: str
    name: str
    exchange: str
    cusip: str
    index_name: str
    category: str
    style: str
    inception: str  # MM/DD/YYYY
    as_of: str  # MM/DD/YYYY
    net_assets: str  # e.g. "$98,169,629,916.13"
    nav: str  # e.g. "$32.33"
    expense: str  # e.g. "0.060%"
    turnover: str  # e.g. "41.96%"
    shares: str  # e.g. "3,036,900,000"
    num_holdings: str  # e.g. "103"


SCHD_FUND = FakeFund(
    ticker="SCHD",
    name="Schwab U.S. Dividend Equity ETF",
    exchange="NYSE Arca, Inc.",
    cusip="808524797",
    index_name="Dow Jones U.S. Dividend 100 Index",
    category="Large Value",
    style="Passive",
    inception="10/20/2011",
    as_of="07/08/2026",
    net_assets="$98,169,629,916.13",
    nav="$32.33",
    expense="0.060%",
    turnover="41.96%",
    shares="3,036,900,000",
    num_holdings="103",
)

SCHF_FUND = FakeFund(
    ticker="SCHF",
    name="Schwab International Equity ETF",
    exchange="NYSE Arca, Inc.",
    cusip="808524805",
    index_name="FTSE Developed ex US Index",
    category="Foreign Large Blend",
    style="Passive",
    inception="11/03/2009",
    as_of="07/08/2026",
    net_assets="$45,123,456,789.00",
    nav="$21.44",
    expense="0.060%",
    turnover="3.50%",
    shares="2,100,000,000",
    num_holdings="1498",
)


def product_html(fund: FakeFund) -> str:
    """A fund-facts <table> shaped like the real one (th=label + trailing td=value)."""

    def row(label: str, value: str) -> str:
        return (
            f'<tr><th scope="row"><strong><span>{label}</span></strong></th>'
            f'<td class="hidden"></td><td>{value}</td></tr>'
        )

    net_assets_row = (
        f'<tr><th scope="row"><strong><span>Total Net Assets</span></strong>'
        f'<div class="sfp-subtitle--small">As of {fund.as_of}</div></th>'
        f'<td class="hidden">{fund.as_of}</td><td>{fund.net_assets}</td></tr>'
    )
    return (
        "<!doctype html><html><head>"
        f"<title>{fund.ticker} | {fund.name} | Schwab Asset Management</title></head><body>"
        f'<a href="/allholdings/{fund.ticker}">See all holdings</a>'
        '<table class="sfm-table"><tbody>'
        + row("Fund Inception", fund.inception)
        + net_assets_row
        + row("Total Expense Ratio", fund.expense)
        + row("Index Name", fund.index_name)
        + row("Shares Outstanding", fund.shares)
        + row("NAV", fund.nav)
        + row("Total Holdings", fund.num_holdings)
        + row("Portfolio Turnover Rate", fund.turnover)
        + row("Morningstar Category", fund.category)
        + row("Management Style", fund.style)
        + row("CUSIP", fund.cusip)
        + row("Exchange", fund.exchange)
        + "</tbody></table></body></html>"
    )


def non_fund_html(slug: str) -> str:
    """A product page for a slug that isn't an ETF (no fund-facts table)."""
    return (
        f"<!doctype html><html><head><title>{slug} | Schwab Asset Management</title></head>"
        "<body><h1>Section landing</h1><p>Marketing copy, no fund facts here.</p></body></html>"
    )


# -- per-fund all-holdings page (paginated) ---------------------------------------


@dataclass(frozen=True)
class FakeHolding:
    name: str
    cusip: str
    symbol: str  # "" for a cash/derivative line
    quantity: str
    weight: str  # e.g. "4.49%"
    market_value: str  # e.g. "$4.4B"


def holdings_html(
    ticker: str,
    rows: list[FakeHolding],
    *,
    as_of: str = "07/08/26",
    total: int | None = None,
    from_: int = 1,
    to: int | None = None,
) -> str:
    """Build ONE all-holdings page: the "As of" header, the "Displaying x-y of N" total, a table."""
    total = total if total is not None else len(rows)
    to = to if to is not None else len(rows)

    def cells(r: FakeHolding) -> str:
        return (
            f"<td>{r.name}</td><td>{r.cusip}</td><td>{r.symbol}</td>"
            f"<td>{r.quantity}</td><td>{r.weight}</td><td>{r.market_value}</td>"
        )

    return (
        "<!doctype html><html><head>"
        f"<title>{ticker} holdings | Schwab Asset Management</title></head><body>"
        f'<div class="header--as-of-date">As of {as_of}</div>'
        f'<div class="count">Displaying {from_} - {to} of {total}</div>'
        '<table class="all-holdings"><thead><tr>'
        '<th scope="col">Fund Name</th><th scope="col">CUSIP</th><th scope="col">Symbol</th>'
        '<th scope="col">Quantity</th><th scope="col">% of Assets</th><th scope="col">Market Value</th>'
        "</tr></thead><tbody>" + "".join(f"<tr>{cells(r)}</tr>" for r in rows) + "</tbody></table></body></html>"
    )


# SCHD holdings split across two pager pages: total 103, page 0 has the top two, page 1 the rest.
SCHD_PAGE0 = [
    FakeHolding("UNITEDHEALTH GROUP INC", "91324P102", "UNH", "10,339,786", "4.49%", "$4.4B"),
    FakeHolding("MERCK &amp; CO INC", "58933Y105", "MRK", "33,985,247", "4.37%", "$4.3B"),
]
SCHD_PAGE1 = [
    FakeHolding("US DOLLAR", "", "", "12,345.67", "0.10%", "$98.1M"),
]

SCHF_HOLDINGS = [
    FakeHolding("NESTLE SA", "", "NESN", "5,000,000", "1.20%", "$1.1B"),
    FakeHolding("ASML HOLDING NV", "", "ASML", "1,200,000", "1.05%", "$980.5M"),
]


def full_router(
    product_by_ticker: dict[str, FakeFund],
    holdings_by_ticker: dict[str, list[FakeHolding]],
) -> Callable[[str], str]:
    """A router covering the full flow: sitemap, each fund's product page, each fund's holdings.

    SCHD paginates (page 0 + page 1); other funds are single-page. Unknown URLs raise (a 404),
    so the driver's skip-on-miss paths are exercised.
    """
    tickers = list(product_by_ticker.keys())

    def route(url: str) -> str:
        if url == SITEMAP_URL:
            return sitemap_xml(tickers)
        for tk in tickers:
            if url == product_page_url(tk):
                return product_html(product_by_ticker[tk])
            if tk == "SCHD":
                if url == holdings_url(tk, 0):
                    return holdings_html(tk, SCHD_PAGE0, total=103, from_=1, to=100)
                if url == holdings_url(tk, 1):
                    return holdings_html(tk, SCHD_PAGE1, total=103, from_=101, to=103)
            elif url == holdings_url(tk, 0):
                rows = holdings_by_ticker.get(tk, [])
                return holdings_html(tk, rows, total=len(rows))
        raise RuntimeError(f"404 for {url}")

    return route
