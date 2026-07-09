"""The Schwab Asset Management driver — pure parsing logic, no VGI/pyarrow import.

Every ``fetch_*`` orchestrator takes an injected ``get(url) -> str`` (HTML/XML text),
so the unit tests drive this module against an in-process fake and the worker wires
the real browser-TLS-impersonating client (:mod:`vgi_etf_schwab.client`). This module
MUST NOT import the VGI SDK — the unit tests import it without the framework.

Three KEYLESS Schwab Asset Management data planes back the read paths, all plain text
served by a Drupal site (see :mod:`vgi_etf_schwab.client` for why they need a
browser-TLS-impersonating transport):

* ``/sitemap.xml`` — the fund UNIVERSE: every ``/products/{slug}`` URL. The ETF tickers
  are the 4-character product slugs (Schwab ETFs are 4-letter tickers; mutual and
  money-market funds are 5-letter).
* ``/products/{ticker}`` — per-fund FACTS for ``products``: a "fund facts" ``<table>``
  of label -> value rows (inception, net assets, expense ratio, NAV, holdings count, …)
  plus the fund name in the ``<title>``. A non-ETF slug has no such table, so
  :func:`parse_product` returns ``None`` and the fund is dropped.
* ``/allholdings/{TICKER}`` — per-fund HOLDINGS for ``holdings``: a paginated ``<table>``
  of constituents (name, CUSIP, symbol, quantity, % of assets, market value) with an
  "As of MM/DD/YY" date and a "Displaying x - y of N" total. Fetched one page at a time
  (``?page=N``) until every constituent is collected.

Schwab publishes CURRENT holdings only, so there is NO as-of/time-travel coordinate;
``as_of_date`` reflects the page's own "as of" date. Every parser is defensive: a
missing field / row / page degrades to an empty result or a ``None`` cell rather than
raising. :func:`resolve_fund` returns ``None`` (not a raise) on an unknown ticker so the
caller can raise a typed SDK error while this module stays SDK-free.

Dates are returned as :class:`datetime.date` (or ``None``); the Arrow mapping to a real
DATE column lives in :mod:`vgi_etf_schwab.schema`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

#: The Schwab Asset Management site host.
SCHWAB_HOST = "https://www.schwabassetmanagement.com"

#: The XML sitemap — the definitive list of Schwab product pages (used to enumerate ETF tickers).
SITEMAP_URL = f"{SCHWAB_HOST}/sitemap.xml"

#: How many holdings rows Schwab renders per pager page.
HOLDINGS_PAGE_SIZE = 100

#: Safety cap on holdings pages fetched per fund (some bond funds list 10k+ constituents).
MAX_HOLDINGS_PAGES = 200

#: The injected transport type: an HTML/XML text ``get``.
Getter = Callable[[str], str]


def product_page_url(ticker: str) -> str:
    """Return a fund's product-page URL (ticker lower-cased into the path)."""
    return f"{SCHWAB_HOST}/products/{ticker.strip().lower()}"


def holdings_url(ticker: str, page: int = 0) -> str:
    """Return a fund's all-holdings URL (ticker upper-cased); ``page`` is the pager index."""
    base = f"{SCHWAB_HOST}/allholdings/{ticker.strip().upper()}"
    return f"{base}?page={page}" if page > 0 else base


# -- shared value coercion --------------------------------------------------------


def _is_blank(v: object) -> bool:
    """Return True for "no data": None, "", "-", "--", "N/A", or all-whitespace."""
    if v is None:
        return True
    if isinstance(v, str):
        t = v.strip()
        return t in ("", "-", "--") or t.upper() == "N/A"
    return False


def _as_str(v: object) -> str | None:
    """Return a trimmed string, or ``None`` for blank/sentinel values."""
    return None if _is_blank(v) else str(v).strip()


_NUM_STRIP_RE = re.compile(r'[$,%"\s]')


def _as_num(v: object) -> float | None:
    """Return a numeric value, stripping ``$ % ,`` quotes and space. ``None`` if not finite."""
    if _is_blank(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(_NUM_STRIP_RE.sub("", str(v)))
    except ValueError:
        return None


_ABBREV_MONEY_RE = re.compile(r"^(-?\d*\.?\d+)([TBMK])?$", re.IGNORECASE)
_ABBREV_STRIP_RE = re.compile(r'[$,\s"]')
_ABBREV_MULT = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}


def parse_abbrev_money(v: object) -> float | None:
    """Parse an abbreviated money string like ``$4.4B`` / ``$871.2M`` into a number of USD.

    Schwab's holdings table shows market value abbreviated (B = billion, M = million,
    K = thousand, T = trillion), so the value is approximate; exact figures are not
    published on the page.
    """
    if _is_blank(v):
        return None
    s = _ABBREV_STRIP_RE.sub("", str(v))
    m = _ABBREV_MONEY_RE.match(s)
    if not m:
        return _as_num(v)
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    suffix = (m.group(2) or "").upper()
    return n * _ABBREV_MULT[suffix] if suffix else n


# -- HTML text helpers ------------------------------------------------------------

_ENTITY_NAMED = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&apos;": "'",
    "&rsquo;": "'",
    "&lsquo;": "'",
    "&nbsp;": " ",
    "&reg;": "®",
}
_ENTITY_APOS_RE = re.compile(r"&#0?39;")
_ENTITY_DEC_RE = re.compile(r"&#(\d+);")
_ENTITY_HEX_RE = re.compile(r"&#x([0-9a-f]+);", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")


def _decode_entities(s: str) -> str:
    """Decode the handful of HTML entities Schwab emits (named + numeric) — best-effort."""
    for name, ch in _ENTITY_NAMED.items():
        s = s.replace(name, ch)
    s = _ENTITY_APOS_RE.sub("'", s)
    s = _ENTITY_DEC_RE.sub(lambda m: chr(int(m.group(1))), s)
    s = _ENTITY_HEX_RE.sub(lambda m: chr(int(m.group(1), 16)), s)
    return s


def html_to_text(html: str) -> str:
    """Strip tags, decode entities, and collapse whitespace — a cell's inner HTML to plain text."""
    return _WS_RE.sub(" ", _decode_entities(_TAG_RE.sub(" ", html))).strip()


# -- date parsing -----------------------------------------------------------------

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_US_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")


def _ymd(y: int, mo: int, d: int) -> date | None:
    """Build a :class:`datetime.date`, returning ``None`` for an invalid y/m/d."""
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_date(v: object) -> date | None:
    """Parse the date shapes Schwab uses into a :class:`datetime.date` (or ``None``).

    * US slash, 4-digit year ``07/08/2026`` (the fund-facts table)
    * US slash, 2-digit year ``07/08/26`` (the holdings "As of" header; ``2000 + YY``)
    * ISO ``2026-07-08`` (defensive)
    """
    if _is_blank(v):
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    m = _ISO_DATE_RE.match(s)
    if m:
        return _ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _US_DATE_RE.match(s)
    if m:
        y = int(m.group(3))
        if len(m.group(3)) == 2:
            y += 2000
        return _ymd(y, int(m.group(1)), int(m.group(2)))
    return None


# -- fund universe (the sitemap) --------------------------------------------------

#: Slugs that look like 4-letter tickers but are Schwab section/marketing pages, not funds.
_NON_FUND_SLUGS = frozenset({"etfs", "home", "star", "stir", "news", "blog"})

_PRODUCTS_SLUG_RE = re.compile(r"/products/([a-z0-9-]+)<", re.IGNORECASE)
_TICKER_SLUG_RE = re.compile(r"^[a-z0-9]{4}$")


def parse_universe(xml: str) -> list[str]:
    """Extract the candidate ETF ticker universe from ``sitemap.xml``.

    Every ``/products/{slug}`` whose slug is a 4-character alphanumeric (Schwab ETF
    tickers are 4 letters; mutual and money-market funds are 5), upper-cased and
    de-duplicated, minus a few known non-fund section pages. A candidate that is not
    actually an ETF is dropped later (its product page has no fund-facts table / its
    holdings page has no table), so this list only needs to be a safe superset.
    """
    out: list[str] = []
    seen: set[str] = set()
    for m in _PRODUCTS_SLUG_RE.finditer(xml):
        slug = m.group(1).lower()
        if not _TICKER_SLUG_RE.match(slug):
            continue
        if slug in _NON_FUND_SLUGS:
            continue
        tk = slug.upper()
        if tk in seen:
            continue
        seen.add(tk)
        out.append(tk)
    out.sort()
    return out


def fetch_universe(get: Getter) -> list[str]:
    """Fetch and parse the fund universe (candidate ETF tickers) from the sitemap. One fetch."""
    return parse_universe(str(get(SITEMAP_URL)))


# -- products (per-fund facts page) -----------------------------------------------


@dataclass(frozen=True, slots=True)
class ProductRow:
    """One row of the ``products`` catalog table — a Schwab ETF's key facts."""

    ticker: str | None
    fund_name: str | None
    exchange: str | None
    cusip: str | None
    index_name: str | None
    morningstar_category: str | None
    management_style: str | None
    inception_date: date | None
    as_of_date: date | None
    net_assets: float | None
    nav: float | None
    expense_ratio_percent: float | None
    portfolio_turnover_percent: float | None
    shares_outstanding: float | None
    num_holdings: float | None


_TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
_TR_RE = re.compile(r"<tr[\s\S]*?</tr>", re.IGNORECASE)
_TH_RE = re.compile(r"<th[\s\S]*?</th>", re.IGNORECASE)
_TD_RE = re.compile(r"<td[\s\S]*?</td>", re.IGNORECASE)
_TBODY_RE = re.compile(r"<tbody[\s\S]*?</tbody>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title>([\s\S]*?)</title>", re.IGNORECASE)
_AS_OF_LABEL_RE = re.compile(r"\bAs of\s+([\d/]+)", re.IGNORECASE)
_AS_OF_STRIP_RE = re.compile(r"\s*As of\s+[\d/]+.*$", re.IGNORECASE)


def parse_product(html: str, ticker: str) -> ProductRow | None:
    """Parse a fund's product page into a :class:`ProductRow`, or ``None`` for a non-ETF page.

    The fund-facts table is the one ``<table>`` that carries both a "CUSIP" and a
    "Total Net Assets" label row; every row is ``<th>Label</th> … <td>Value</td>`` (the
    value is the LAST ``<td>``; an "As of …" date may ride along in the label). ``ticker``
    is passed in (the slug) and the fund name is read from the page's ``<title>``
    (``TICKER | Fund Name | Schwab Asset Management``).
    """
    tables = _TABLE_RE.findall(html)
    facts_table = next((t for t in tables if "CUSIP" in t and "Total Net Assets" in t), None)
    if facts_table is None:
        return None

    facts: dict[str, tuple[str, date | None]] = {}
    for tr in _TR_RE.findall(facts_table):
        th = _TH_RE.search(tr)
        tds = _TD_RE.findall(tr)
        if th is None or not tds:
            continue
        label_raw = html_to_text(th.group(0))
        as_of_m = _AS_OF_LABEL_RE.search(label_raw)
        label = _AS_OF_STRIP_RE.sub("", label_raw).strip()
        value = html_to_text(tds[-1])
        if label:
            facts[label] = (value, parse_date(as_of_m.group(1)) if as_of_m else None)

    def fact(label: str) -> str | None:
        entry = facts.get(label)
        return _as_str(entry[0]) if entry is not None else None

    def fact_as_of(label: str) -> date | None:
        entry = facts.get(label)
        return entry[1] if entry is not None else None

    fund_name: str | None = None
    title_m = _TITLE_RE.search(html)
    if title_m:
        parts = [p.strip() for p in html_to_text(title_m.group(1)).split("|")]
        if len(parts) >= 2:
            fund_name = parts[1] or None

    return ProductRow(
        ticker=ticker.strip().upper(),
        fund_name=fund_name,
        exchange=fact("Exchange"),
        cusip=fact("CUSIP"),
        index_name=fact("Index Name"),
        morningstar_category=fact("Morningstar Category"),
        management_style=fact("Management Style"),
        inception_date=parse_date(fact("Fund Inception")),
        as_of_date=fact_as_of("Total Net Assets") or fact_as_of("NAV"),
        net_assets=_as_num(fact("Total Net Assets")),
        nav=_as_num(fact("NAV")),
        expense_ratio_percent=_as_num(fact("Total Expense Ratio")),
        portfolio_turnover_percent=_as_num(fact("Portfolio Turnover Rate")),
        shares_outstanding=_as_num(fact("Shares Outstanding")),
        num_holdings=_as_num(fact("Total Holdings")),
    )


def fetch_products(get: Getter, ticker: str = "") -> list[ProductRow]:
    """Fetch the whole ETF catalog (or one fund when ``ticker`` is given).

    Enumerate the universe from the sitemap, fetch each fund's product page, parse its
    facts, and drop candidates that are not ETF fund pages. A per-fund fetch that raises
    (e.g. a 404 on a non-fund slug) is skipped, never fatal.
    """
    universe = fetch_universe(get)
    want = ticker.strip().upper()
    if want:
        universe = [t for t in universe if t == want]
    rows: list[ProductRow] = []
    for tk in universe:
        try:
            row = parse_product(str(get(product_page_url(tk))), tk)
        except Exception:
            row = None
        if row is not None and row.cusip is not None:
            rows.append(row)
    return rows


# -- ticker resolution (validate + canonicalize against the universe) -------------


def resolve_fund(get: Getter, fund: str) -> str | None:
    """Resolve a ``fund`` argument to a canonical ticker by matching the sitemap universe.

    Case-insensitive. Returns ``None`` when the ticker isn't a Schwab ETF candidate (the
    caller raises a typed error — this module stays SDK-free). One sitemap fetch.
    """
    wanted = fund.strip().upper()
    if not wanted:
        return None
    return wanted if wanted in fetch_universe(get) else None


# -- holdings (the paginated all-holdings page) -----------------------------------


@dataclass(frozen=True, slots=True)
class HoldingRow:
    """One constituent row of the ``holdings`` table for a given fund."""

    #: The fund's ticker — the partition key (constant per fund; distinct from ``ticker``).
    fund_ticker: str | None
    as_of_date: date | None
    weight_percent: float | None
    #: Constituent ticker (the "Symbol" column; blank for cash/derivative lines).
    ticker: str | None
    name: str | None
    cusip: str | None
    quantity: float | None
    #: Market value in USD — Schwab shows this ABBREVIATED (e.g. ``$4.4B``), so it is approximate.
    market_value: float | None


@dataclass(frozen=True, slots=True)
class HoldingsPage:
    """The parsed contents of a single all-holdings pager page."""

    rows: list[HoldingRow]
    #: Total constituent count from the "Displaying x - y of N" header, or ``None`` if absent.
    total: float | None
    as_of: date | None


def _header_columns(header_row: str) -> dict[str, int]:
    """Map a lower-cased holdings-table header label to its column index."""
    out: dict[str, int] = {}
    for c, th in enumerate(_TH_RE.findall(header_row)):
        name = html_to_text(th).lower()
        if name and name not in out:
            out[name] = c
    return out


_DISPLAYING_RE = re.compile(r"Displaying\s+[\d,]+\s*(?:-|–|to)\s*[\d,]+\s+of\s+([\d,]+)", re.IGNORECASE)
_WEIGHT_HEADER_RE = re.compile(r"%\s*of\s*Assets", re.IGNORECASE)


def parse_holdings_page(html: str, fund_ticker: str | None) -> HoldingsPage:
    """Parse ONE all-holdings page.

    Reads the holdings ``<table>`` (the one whose header carries "% of Assets"),
    header-driven so a reordered/augmented column set still binds; the page's
    "As of MM/DD/YY" date; and the "Displaying x - y of N" total (to drive pagination).
    Returns empty rows when there is no holdings table (e.g. a non-ETF slug's page).
    """
    as_of_m = _AS_OF_LABEL_RE.search(html)
    as_of = parse_date(as_of_m.group(1)) if as_of_m else None
    total_m = _DISPLAYING_RE.search(html)
    total = _as_num(total_m.group(1)) if total_m else None

    tables = _TABLE_RE.findall(html)
    table = next((t for t in tables if _WEIGHT_HEADER_RE.search(t)), None)
    if table is None:
        return HoldingsPage(rows=[], total=total, as_of=as_of)

    head_row = _TR_RE.search(table)
    if head_row is None:
        return HoldingsPage(rows=[], total=total, as_of=as_of)
    cols = _header_columns(head_row.group(0))

    def col(*labels: str) -> int | None:
        for label in labels:
            if label in cols:
                return cols[label]
        return None

    symbol_col = col("symbol", "ticker")
    name_col = col("fund name", "name", "security name")
    cusip_col = col("cusip")
    qty_col = col("quantity", "shares")
    weight_col = col("% of assets", "% of net assets")
    mv_col = col("market value")

    body_m = _TBODY_RE.search(table)
    body_html = body_m.group(0) if body_m else table
    rows: list[HoldingRow] = []
    for tr in _TR_RE.findall(body_html):
        tds = _TD_RE.findall(tr)
        if not tds:
            continue

        def cell(i: int | None, tds: list[str] = tds) -> str | None:
            return None if i is None or i >= len(tds) else html_to_text(tds[i])

        weight = _as_num(cell(weight_col))
        name = cell(name_col)
        if weight is None and name is None:
            continue  # skip a footer/disclaimer row
        rows.append(
            HoldingRow(
                fund_ticker=fund_ticker,
                as_of_date=as_of,
                weight_percent=weight,
                ticker=_as_str(cell(symbol_col)),
                name=name,
                cusip=_as_str(cell(cusip_col)),
                quantity=_as_num(cell(qty_col)),
                market_value=parse_abbrev_money(cell(mv_col)),
            )
        )
    return HoldingsPage(rows=rows, total=total, as_of=as_of)


def page_count(total: float | None) -> int:
    """Return how many pager pages a total-count implies (page 0 is the first page size)."""
    if total is None or total <= HOLDINGS_PAGE_SIZE:
        return 1
    return min(-(-int(total) // HOLDINGS_PAGE_SIZE), MAX_HOLDINGS_PAGES)


def fetch_holdings(get: Getter, fund_ticker: str, max_pages: int = MAX_HOLDINGS_PAGES) -> list[HoldingRow]:
    """Return all CURRENT holdings for one fund, sorted weight-descending (NULLS last).

    Fetches page 0 to learn the total, then the remaining pages (bounded), concatenating
    every constituent. A fund whose page has no holdings table (e.g. a non-ETF slug's page)
    returns an empty list — but a TRANSPORT error on page 0 (a 403/blocked wall, a 5xx, a
    network failure) is PROPAGATED, not swallowed: a reachability failure should surface as
    an error rather than masquerade as an empty fund. Later pages are best-effort (a
    mid-pagination error just truncates the result).
    """
    tk = fund_ticker.strip().upper()
    first = parse_holdings_page(str(get(holdings_url(tk, 0))), tk)
    rows = list(first.rows)
    pages = min(page_count(first.total), max_pages)
    for p in range(1, pages):
        try:
            pg = parse_holdings_page(str(get(holdings_url(tk, p))), tk)
        except Exception:
            break
        if not pg.rows:
            break
        rows.extend(pg.rows)
    rows.sort(key=lambda r: r.weight_percent if r.weight_percent is not None else float("-inf"), reverse=True)
    return rows
