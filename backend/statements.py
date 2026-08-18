"""Reading figures out of a financial statement.

The primitives every other module uses to get a number off an income statement,
balance sheet or cash-flow statement: latest value, value at a named period, a
series, the two derived quantities that are only meaningful with their period
attached (`statement_fcf`, `paired_latest`), and the balance-sheet bridge terms.

Pure functions over the nested dicts `data_provider.get_fundamentals` returns.
Nothing here imports anything else in this package, and nothing here knows what a
valuation is — which is the point. These lived inside `financial_models` until
2026-08-18, where they were the module's most-used export and, being
underscore-prefixed, also its most-used *private* export: `scoring` reached
through it for eleven of them, `main` for one, and `sector_weights`' docstring
cited a twelfth. A valuation module is not where you look for "read net income",
and a private name three other modules depend on is public API wearing a
disguise.

Every period argument is a `YYYY-MM-DD` string keyed on statement-period end.
Where a function can pair two figures, it returns the period alongside them: a
ratio built from two different years is the recurring defect this module exists
to prevent, and the docstrings below record each time it happened.
"""
from __future__ import annotations


def latest(statement: dict, *row_names):
    """Most recent non-null value for any of the given row names."""
    for period in sorted(statement.keys(), reverse=True):
        rows = statement[period]
        for name in row_names:
            v = rows.get(name)
            if v is not None:
                return v
    return None


def value_at(statement: dict, period: str, *row_names):
    """Value for the given period only — used where two figures must share a period."""
    rows = statement.get(period)
    if not rows:
        return None
    for name in row_names:
        if rows.get(name) is not None:
            return rows[name]
    return None


def equity_bridge(bal: dict, period: str | None) -> dict:
    """The EV→equity terms beyond net debt, read from one balance-sheet date.

    `financial-models-reference.md` §1.1 states the bridge as five terms:

        Equity = EV - Net Debt - Minority Interest - Preferred + Non-operating Assets

    The model implemented one. The other three are on the balance sheet the app
    already fetches, and on 0700.HK they are worth 28% of enterprise value —
    enough to reverse its verdict — while on the other six fixtures they are
    worth 1-4pp. Absent, they are not merely imprecise: a reader sees a fair
    value that silently excludes a quarter of the company.

    Three of the terms are read; the fourth is only reported.

      minority_interest, preferred   subtracted. Book value is the conventional
                                     basis for both, and the reference doc asks
                                     for them by name.
      marked_securities             added. `Investmentin Financial Assets` is
                                     exactly `Available For Sale Securities` +
                                     `Financial Assets at FVTPL` (verified on
                                     both of 0700.HK's reported periods), and
                                     both of those are *already carried at fair
                                     value*. Using them reads a filed mark; it
                                     does not make one.
      associates_at_cost            returned, never added. Held at cost, and
                                     cost is not value — that is a judgement the
                                     platform does not make. Same treatment as
                                     the normalised base year: shown beside the
                                     headline, excluded from it.

    `Long Term Equity Investment` is the parent of `Investmentsin Associatesat
    Cost` and `Investmentsin Joint Venturesat Cost` — on 0700.HK the three
    satisfy 342,409 + 6,303 = 348,712 exactly, in both reported periods. Reading
    the parent is what avoids the double count that kept this unimplemented;
    never sum the children. Issuers that report no children still report the
    parent, so nothing is lost by ignoring them.

    **Period-pinned, and deliberately without a fallback.** `value_at` reads one
    date; `latest` would walk backwards until it found a number. MSFT is the
    live case: its `Long Term Equity Investment` row exists at 2025-06-30 and is
    absent at 2026-06-30, so a fallback would import a year-old balance into
    today's valuation. This codebase has been bitten by exactly that twice — see
    `paired_latest` below, where interest coverage was FY2025 EBIT over FY2023
    interest. A row that is not reported is unknown, and unknown stays out.

    An absent row is read as zero here, unlike the net-debt legs, and the
    difference is deliberate. Every issuer has debt and cash, so a missing
    `totalDebt` is a vendor failure worth naming. Most issuers genuinely have no
    preferred stock and no associates, so a missing row is the balance sheet
    saying "nil" — flagging it would put a warning on all seven fixtures and
    teach the reader to ignore warnings.

    What *is* worth naming is a row that **used to be reported and no longer
    is**, which is a real signal and a real defect this vendor produces: MSFT
    carried `Long Term Equity Investment` at 2025-06-30 and carries nothing at
    2026-06-30. That may be a disposal or a dropped row, and the filing does not
    say which — so it is reported as `disappeared` rather than guessed at.
    """
    out = {"minority_interest": 0.0, "preferred": 0.0, "marked_securities": 0.0,
           "associates_at_cost": 0.0, "period": period, "disappeared": []}
    if not period:
        return out

    earlier = [p for p in bal if p < period]
    for key, names in (
        ("minority_interest", ("Minority Interest",)),
        ("preferred", ("Preferred Stock", "Preferred Securities Outside Stock Equity")),
        ("marked_securities", ("Investmentin Financial Assets",)),
        ("associates_at_cost", ("Long Term Equity Investment",)),
    ):
        value = value_at(bal, period, *names)
        if value is None:
            if any(value_at(bal, p, *names) is not None for p in earlier):
                out["disappeared"].append(key)
        else:
            out[key] = float(value)
    return out


def paired_latest(statement: dict, names_a: tuple, names_b: tuple):
    """(period, a, b) from the newest period reporting **both**, else None.

    Two independent `latest` calls will happily pair this year's numerator with
    a years-old denominator, because each walks back until it finds anything.
    Measured on the AAPL fixture 2026-08-10: `latest` for EBIT resolves
    2025-09-30 while `latest` for Interest Expense resolves 2023-09-30 — yfinance
    stopped reporting the row — so the interest coverage on screen was FY2025
    operating income over FY2023 interest, a ratio of two different businesses.

    This is the same discipline `statement_fcf` enforces by returning its period
    and `fcf_conversion` inherits from it: a ratio is only a ratio when both legs
    describe one period. A stale-but-consistent answer beats a fresh-looking
    mixed one, and the period is returned so callers can say which year it is.
    """
    for period in sorted(statement.keys(), reverse=True):
        a = value_at(statement, period, *names_a)
        b = value_at(statement, period, *names_b)
        if a is not None and b is not None:
            return period, a, b
    return None


EBIT_ROWS = ("EBIT", "Operating Income")
INTEREST_ROWS = ("Interest Expense",)


def interest_coverage(income_statement: dict):
    """(coverage, period) — EBIT over interest expense, both from one period."""
    pair = paired_latest(income_statement, EBIT_ROWS, INTEREST_ROWS)
    if pair is None:
        return None, None
    period, ebit, interest = pair
    if not interest:
        return None, period
    return ebit / abs(interest), period


def series(statement: dict, *row_names) -> list[tuple[str, float]]:
    """(period, value) oldest-first for the first row name that has data."""
    out = []
    for period in sorted(statement.keys()):
        rows = statement[period]
        for name in row_names:
            if rows.get(name) is not None:
                out.append((period, rows[name]))
                break
    return out


def statement_fcf(cash_flow: dict) -> tuple[str, float] | None:
    """(period, **levered** FCF) from the newest period reporting both legs.

    CapEx is negative, so this is `CFO - CapEx`. Under US GAAP interest paid sits
    inside operating cash flow, which makes this a levered measure — closer to
    free cash flow to equity before net borrowing than to FCFF. That is the right
    quantity for `scoring.fcf_yield` (divided by market cap) and
    `scoring.fcf_conversion` (divided by net income), both of which are after
    interest. It is **not** the right quantity to discount at WACC:
    `dcf_valuation` adds interest back through `fcff_interest_addback` instead.
    Do not "fix" this function — three of its four callers want it levered.

    Returns the period as well as the value so callers that divide FCF by another
    statement figure can demand the same period. Mixing this year's operating
    cash flow with last year's CapEx — or this year's FCF with last year's net
    income — would silently distort the result.
    """
    for period in sorted(cash_flow.keys(), reverse=True):
        rows = cash_flow[period]
        ocf = rows.get("Operating Cash Flow")
        if ocf is None:
            ocf = rows.get("Cash Flow From Continuing Operating Activities")
        capex = rows.get("Capital Expenditure")
        if ocf is not None and capex is not None:
            return period, ocf + capex
    return None


def fcff_interest_addback(cash_flow: dict, period: str | None,
                          tax_rate: float) -> tuple[float, str]:
    """(after-tax interest to add back, basis) turning levered FCF into FCFF.

    `statement_fcf` is levered where interest paid runs through operating
    activities, so discounting it at WACC *and* subtracting net debt would charge
    the debt twice. The add-back is `Interest x (1 - Tc)`.

    Whether it applies at all is **read from the statement, not assumed**. US
    GAAP requires interest paid to be disclosed as supplemental data alongside an
    operating-activities classification; IFRS permits classifying it in
    financing, in which case operating cash flow is *already* unlevered and
    adding interest back would overstate FCFF rather than correct it. Measured
    2026-08-09 across the fixtures: 0700.HK reports `Interest Paid Cff` in all
    four captured periods (and `Interest Received Cfi`, so its interest income is
    outside operating too), while every US filer reports `Interest Paid
    Supplemental Data`. Keying on the row that is actually present means a new
    IFRS listing is handled correctly without anyone having to know its GAAP.

    The cash figure is used rather than the income statement's accrual, because
    the quantity being adjusted is cash. The two diverge when interest is
    capitalised — XOM's accrual is 603M against 1,752M paid, a factor of 2.9.

    Interest *income* is deliberately not netted off: on a cash basis US filers
    disclose no matching "interest received" row, so netting would mean adding a
    cash figure and subtracting an accrual one. The consequence is that cash is
    valued twice for a net-cash issuer — once through the `EV - net_debt` bridge
    and once through the perpetual interest it earns inside operating cash flow.
    Measured, that is worth about +3% of FCF on MSFT and AAPL.

    Returns 0.0 with a stated reason whenever the adjustment cannot be justified,
    so an unverifiable case is left alone rather than guessed at.
    """
    if period is None:
        return 0.0, "no_statement_fcf"
    rows = cash_flow.get(period) or {}
    if rows.get("Interest Paid Cff") is not None:
        return 0.0, "not_required_interest_in_financing"
    cash_interest = rows.get("Interest Paid Supplemental Data")
    if cash_interest is not None:
        # Disclosed as an outflow; sign convention varies, magnitude does not.
        return abs(cash_interest) * (1 - tax_rate), "cash_interest_paid"
    return 0.0, "unverified_interest_classification"
