"""Peer comparison (trading comps) and valuation-range (football field) assembly.

Peer suggestions are curated-first: FMP peer discovery is measurably worse than
the hand-curated list where one exists (UPS -> HWM, GD, MMM, WM — generic
industrials rather than freight), but it covers HK and turns "no peers at all"
into "usually usable" for the ~everything else. Users can always edit the peer
list in the UI, so a bad suggestion is visible and correctable.
"""
from __future__ import annotations

from statistics import median, quantiles

from backend import financial_models as fm
from backend import sector_weights
from backend.data_provider import provider

PEER_SUGGESTIONS = {
    # US mega-cap tech
    "AAPL": ["MSFT", "GOOGL", "META", "AMZN"],
    "MSFT": ["AAPL", "GOOGL", "AMZN", "ORCL"],
    "GOOGL": ["META", "MSFT", "AMZN", "AAPL"],
    "META": ["GOOGL", "SNAP", "PINS", "MSFT"],
    "AMZN": ["MSFT", "GOOGL", "WMT", "BABA"],
    "NVDA": ["AMD", "AVGO", "INTC", "QCOM"],
    "AMD": ["NVDA", "INTC", "QCOM", "AVGO"],
    "TSLA": ["BYDDY", "GM", "F", "RIVN"],
    "NFLX": ["DIS", "WBD", "PARA", "ROKU"],
    # US financials / consumer / health / energy
    "JPM": ["BAC", "WFC", "C", "GS"],
    "V": ["MA", "AXP", "PYPL", "FI"],
    "JNJ": ["PFE", "MRK", "ABBV", "LLY"],
    "WMT": ["TGT", "COST", "KR", "AMZN"],
    "KO": ["PEP", "KDP", "MNST", "CELH"],
    "XOM": ["CVX", "COP", "SHEL", "BP"],
    "UPS": ["FDX", "GXO", "CHRW", "EXPD"],
    "FDX": ["UPS", "GXO", "CHRW", "EXPD"],
    # HK
    "0700.HK": ["9988.HK", "3690.HK", "9999.HK", "1024.HK"],
    "9988.HK": ["0700.HK", "3690.HK", "9618.HK", "PDD"],
    "3690.HK": ["9988.HK", "0700.HK", "9618.HK", "1024.HK"],
    "0005.HK": ["2388.HK", "0011.HK", "1398.HK", "3988.HK"],
    "1299.HK": ["2318.HK", "2628.HK", "0966.HK", "PRU"],
    "0941.HK": ["0728.HK", "0762.HK", "T", "VZ"],
}

MULTIPLE_KEYS = ["pe_trailing", "pe_forward", "price_to_book",
                 "ev_to_ebitda", "ev_to_revenue", "peg_ratio"]

# Which peer median each implied value rests on, so the football field can say
# how thin the thinnest one is rather than quoting the peer count and implying
# every multiple had that much support.
IMPLIED_TO_MULTIPLE = {
    "peer_forward_pe": "pe_forward",
    "peer_trailing_pe": "pe_trailing",
    "peer_ev_ebitda": "ev_to_ebitda",
    "peer_ev_revenue": "ev_to_revenue",
    "peer_price_to_book": "price_to_book",
}


MAX_AUTO_PEERS = 4

# How far the target's operating margin may sit from the peer median before a
# peer EV/Revenue multiple stops transferring. See `_ev_revenue_transfers`.
EV_REVENUE_MARGIN_TOLERANCE = 2.0

# Sell-side target ranges below this many contributing analysts are one or two
# opinions wearing the costume of a range. Same threshold as the analyst signal
# in scoring.py, deliberately: one rule, one number.
MIN_ANALYST_OPINIONS = 4

# How far apart the analysts are, as (high - low) / mean.
#
# The target *range* is excluded from the valuation for good reasons — it
# forecasts a price rather than valuing a business — but its *width* answers a
# different question the platform was throwing away: how much do informed
# observers disagree about this company? That is an uncertainty signal, not a
# valuation one, so it is reported beside the conviction grade rather than
# folded into it.
#
# Round thresholds rather than fitted ones, checked against a 20-name panel
# measured 2026-08-13 (min 15.4% on O, median 41.5%, max 105.7% on NVDA) only to
# confirm they discriminate: they split it 6 tight / 11 moderate / 3 wide. They
# are not calibrated against outcomes and no part of the score depends on them.
ANALYST_DISPERSION_TIGHT, ANALYST_DISPERSION_WIDE = 0.30, 0.60

# Method-midpoint spread bands from the reference doc's conviction table
# (§5.2). Above DIVERGENCE_CALLOUT the doc's instruction is explicit: do not
# average into false precision, report both anchors and name the assumption
# that separates them.
CONVICTION_HIGH, CONVICTION_MEDIUM = 0.15, 0.30
DIVERGENCE_CALLOUT = 0.40

_FMP_PEER_CACHE: dict[str, list[str]] = {}


def _fmp_peers(ticker: str) -> list[str]:
    """FMP peer discovery — free tier, no extra key beyond the configured one.

    Successes are cached for the process lifetime; failures are **not**, so a
    transient outage does not permanently blank a ticker's peers (same rule as
    data_provider.risk_free_rate).
    """
    if ticker in _FMP_PEER_CACHE:
        return _FMP_PEER_CACHE[ticker]
    try:
        # deferred: importing openbb costs ~5 s, so only a request that actually
        # needs discovery pays it, and only once per process
        from openbb import obb
        rows = obb.equity.compare.peers(symbol=ticker, provider="fmp").results
        peers = [r.symbol for r in rows if getattr(r, "symbol", None)][:MAX_AUTO_PEERS]
    except Exception:
        return []  # EmptyDataError for unknown tickers, plus network/quota failures
    if peers:
        _FMP_PEER_CACHE[ticker] = peers
    return peers


def suggest_peers(ticker: str) -> list[str]:
    """Curated list when we have one, FMP discovery otherwise."""
    t = ticker.upper()
    return PEER_SUGGESTIONS.get(t) or _fmp_peers(t)


def peer_beta_inputs(ticker: str) -> list[dict]:
    """Suggested peers' snapshots, for financial_models.resolve_beta.

    Returns whole snapshots rather than bare betas because resolve_beta unlevers
    each peer beta before taking the median, which needs that peer's own
    `total_debt` and `market_cap` — both already on the snapshot.

    Reads through the TTL-cached peer snapshot, so on a warm cache this costs
    nothing. Callers should only reach for this when the company's own reported
    beta is not credible — see main.py.
    """
    out = []
    for p in suggest_peers(ticker):
        try:
            snap = provider.get_peer_snapshot(p)
        except Exception:
            continue
        if snap.get("beta") is not None:
            out.append(snap)
    return out


def _pct(x: float | None) -> str:
    return "unknown" if x is None else f"{x:.1%}"


def _ev_revenue_transfers(target_margin: float | None,
                          peer_margin: float | None) -> bool:
    """Whether a peer EV/Revenue multiple can be carried onto the target.

    A revenue multiple is a margin assumption wearing a multiple's clothes: two
    businesses on identical revenue and different margins do not deserve the
    same EV/Sales. Measured live 2026-08-12 on 0700.HK, the curated peer set's
    median operating margin was **5.7%** (9988 1.0%, 3690 -7.5%, 1024 10.5%)
    against Tencent's **34.3%**, and the peer median 1.84x revenue multiple
    implied **189.61** a share against a 439-471 cluster from every other
    multiple. That one number stretched the football-field bar to 2.48x wide and
    was the sole reason its verdict still read "in range" — a bar that broad
    contains any price, which is exactly the criticism the DCF bar was already
    fixed for.

    Comparability is *verified rather than assumed*, the same shape as the P/B
    sector gate below: an unknown margin on either side means no multiple. The
    one exception is a peer set and a target that are both loss-making, where
    EV/Sales is the conventional multiple precisely because earnings are not
    available yet — `sector_weights.pre_profit_growth` scores `ev_sales` for the
    same reason.
    """
    if target_margin is None or peer_margin is None:
        return False
    if target_margin <= 0 or peer_margin <= 0:
        return target_margin <= 0 and peer_margin <= 0
    return 1 / EV_REVENUE_MARGIN_TOLERANCE <= target_margin / peer_margin \
        <= EV_REVENUE_MARGIN_TOLERANCE


def comps_analysis(target_fund: dict, peer_tickers: list[str]) -> dict:
    """Comps table + peer-median-implied share values for the target."""
    info = target_fund["info"]
    # Target and peers alike are restated onto one currency before anything is
    # compared or medianed. Correcting only one side would be worse than
    # correcting neither: an all-HK peer set carries the same vendor mismatch,
    # so a corrected target beside uncorrected peers would read 10% cheap purely
    # on FX. See fm.ev_multiple_one_currency.
    target_ev_ebitda, target_ev_revenue = fm.ev_multiples_for(info)
    target_row = {
        "ticker": target_fund["ticker"],
        "name": info.get("longName"),
        "market_cap": info.get("marketCap"),
        "pe_trailing": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "price_to_book": info.get("priceToBook"),
        "ev_to_ebitda": target_ev_ebitda,
        "ev_to_revenue": target_ev_revenue,
        "peg_ratio": info.get("pegRatio"),
        "operating_margin": info.get("operatingMargins"),
        "revenue_growth": info.get("revenueGrowth"),
    }

    peers, failed = [], []
    for p in peer_tickers[:8]:
        try:
            snap = provider.get_peer_snapshot(p)
            if snap["market_cap"] is None:
                failed.append(p)
            else:
                # Each peer carries its own pair — an HK peer set mixes
                # HKD-reporting and CNY-reporting names, so the rate is per peer
                # and not the target's.
                for key in ("ev_to_ebitda", "ev_to_revenue"):
                    snap[key] = fm.ev_multiple_one_currency(
                        snap.get(key), snap.get("currency"), snap.get("financial_currency"))
                peers.append(snap)
        except Exception:
            failed.append(p)

    # The count behind each median, not just the peer count. They differ: a peer
    # whose multiple is negative or missing is filtered by the positive-only rule
    # below but still counts as a resolved peer, so "4 peers" can mean a median
    # of 3. Measured 2026-08-12, 0700.HK's EV/EBITDA median rested on three of
    # its four peers — 3690.HK reported -12.505.
    medians, median_n = {}, {}
    for key in MULTIPLE_KEYS:
        vals = [p[key] for p in peers if p[key] is not None and p[key] > 0]
        medians[key] = round(median(vals), 2) if vals else None
        median_n[key] = len(vals)

    # apply peer-median multiples to the target's own metrics
    shares = info.get("sharesOutstanding")
    net_debt = (info.get("totalDebt") or 0) - (info.get("totalCash") or 0)
    implied = {}

    # An EV multiple times a statement figure lands in the reporting currency,
    # as does net debt, so the bridged per-share value has to be converted before
    # it can sit on a football field beside a trading-currency price. The
    # earnings multiples below need no conversion: EPS is already trading-currency.
    fx, fx_mismatch = fm.statement_to_market_fx(
        info.get("currency"), info.get("financialCurrency"))

    def ev_implied(mult, metric):
        if mult and metric and shares and fx is not None:
            return round((mult * metric - net_debt) * fx / shares, 2)
        return None

    if medians.get("pe_forward") and info.get("forwardEps"):
        implied["peer_forward_pe"] = round(medians["pe_forward"] * info["forwardEps"], 2)
    if medians.get("pe_trailing") and info.get("trailingEps"):
        implied["peer_trailing_pe"] = round(medians["pe_trailing"] * info["trailingEps"], 2)
    implied["peer_ev_ebitda"] = ev_implied(medians.get("ev_to_ebitda"), info.get("ebitda"))

    # EV/Revenue only where the margins make it a comparison — see
    # `_ev_revenue_transfers`. Suppression is recorded rather than silent,
    # because a missing multiple that nobody explains reads as missing data.
    suppressed: dict[str, str] = {}
    peer_margins = [p["operating_margin"] for p in peers
                    if p.get("operating_margin") is not None]
    peer_margin = median(peer_margins) if peer_margins else None
    if _ev_revenue_transfers(info.get("operatingMargins"), peer_margin):
        implied["peer_ev_revenue"] = ev_implied(medians.get("ev_to_revenue"),
                                                info.get("totalRevenue"))
    elif medians.get("ev_to_revenue"):
        suppressed["peer_ev_revenue"] = (
            "Operating margin "
            f"{_pct(info.get('operatingMargins'))} against a peer median of "
            f"{_pct(peer_margin)} — a revenue multiple does not transfer across "
            "that gap.")

    # P/B-implied value is only meaningful for balance-sheet-driven sectors
    if info.get("sector") in ("Financial Services", "Real Estate") \
            and medians.get("price_to_book") and info.get("bookValue"):
        implied["peer_price_to_book"] = round(medians["price_to_book"] * info["bookValue"], 2)
    implied = {k: v for k, v in implied.items() if v is not None and v > 0}

    return {
        "target": target_row,
        "peers": peers,
        "failed_tickers": failed,
        "peers_used": len(peers),
        "peer_medians": medians,
        "peer_medians_n": median_n,
        "peer_operating_margin": peer_margin,
        "implied_values": implied,
        "suppressed_multiples": suppressed,
        "implied_range": {
            "low": min(implied.values()) if implied else None,
            "high": max(implied.values()) if implied else None,
        },
    }


def _dcf_band(dcf: dict) -> tuple[float, float, str] | None:
    """(low, high, basis) for the DCF bar, or None when the grid is empty.

    The 25th-75th percentile of the sensitivity grid, per the reference doc's
    football-field spec (§5.2), not the grid's min/max. The grid's corners are
    the compounded worst and best case of two assumptions moved together, so
    min/max produced a bar roughly twice as wide as the band the method actually
    supports: measured 2026-08-07, AAPL 55.27 -> 26.73, MSFT 132.95 -> 64.00,
    0700.HK 330.00 -> 149.08.

    The grid alone understates the DCF, though, because it stresses WACC and
    terminal growth — the two *second-order* assumptions — while holding the
    first-order one fixed. `growth_sensitivity` carries the base rate swept
    +/-4pp, and its full span is unioned in rather than pooled into the
    quartiles: five growth points against twenty-five grid cells would barely
    move a quartile, which would hide exactly the driver the band exists to
    show. Measured live 2026-08-12 on 0700.HK, the grid alone gave 606.74-778.12
    and a confident "price below"; growth from 9.38% to 4% alone gives 502.96,
    which is the assumption the verdict actually rests on.
    """
    vals = sorted(v for row in dcf["sensitivity"]["rows"]
                  for v in row["values"] if v is not None)
    if not vals:
        return None
    if len(vals) >= 4:
        low, high = quantiles(vals, n=4)[0], quantiles(vals, n=4)[2]
        basis = "sensitivity 25th–75th"
    else:
        low, high = min(vals), max(vals)
        basis = "sensitivity range"
    growth = [v for v in (dcf.get("growth_sensitivity") or {}).get("values", [])
              if v is not None]
    if growth:
        extended_low, extended_high = min(growth) < low, max(growth) > high
        low, high = min(low, *growth), max(high, *growth)
        # Name only the sides the sweep actually reached. A flat "+ growth" read
        # as a symmetric stress even where the sweep contributed to one end and
        # nothing to the other, which is how a one-sided band used to pass for a
        # balanced one.
        if extended_low and extended_high:
            basis += " + growth"
        elif extended_low:
            basis += " + growth (downside only)"
        elif extended_high:
            basis += " + growth (upside only)"

    # The base year is the third assumption in the bar, and until now the only
    # one it did not carry. Both sweeps above move a *rate* while holding the
    # level they are applied to fixed, so neither can express what the starting
    # year being unrepresentative would do — and a level error in base FCF is
    # undamped, since fair value is homogeneous of degree one in it.
    #
    # This is the union, not a substitution: the tick stays on the reported-year
    # answer, and `enterprise_value(..., base=normalised)` is the other end of a
    # band the platform declines to choose between. Measured on the fixtures
    # (risk-free pinned at 4.3%) it widens upward for XOM 71.75 -> 102.17 and
    # MSFT 248.51 -> 321.75, and *downward* for 0700.HK 663.32 -> 628.00. That
    # it is not one-directional is the whole reason it can be shown without
    # taking a view: a rule that only ever raised the value would be price
    # tuning wearing a band's clothes.
    normalised = ((dcf.get("diagnostics") or {}).get("base_year") or {}).get(
        "fair_value_normalised")
    # `> 0` for the same reason price_gap_bridge uses it: a normalised
    # enterprise value below net debt gives a negative per-share figure, and a
    # bar stretched to it would be unreadable rather than merely wide.
    if normalised is not None and normalised > 0:
        # One value can only ever reach one side, so the growth sweep's
        # two-sided wording does not transfer. Naming it only when it actually
        # widened the bar keeps the same rule: the basis lists what moved the
        # edges, and a normalised figure already inside the band moved nothing.
        if normalised < low or normalised > high:
            basis += " + base year"
        low, high = min(low, normalised), max(high, normalised)
    return round(low, 2), round(high, 2), basis


def _clamped_mid(mid, low: float, high: float):
    """A midpoint tick that cannot render outside its own bar.

    `mid` is the model's base-case answer rather than the band's centre, which
    is the right number to show — but nothing guarantees it lands inside a band
    built from quantiles over a grid with dropped cells, and the chart positions
    the tick with no bounds check of its own.
    """
    return None if mid is None else min(max(mid, low), high)


def football_field(target_fund: dict, dcf: dict, comps: dict,
                   classification: str | None = None) -> list[dict]:
    """Valuation ranges from each method, for the range chart.

    `classification` gates the DCF row. Without it the only test available was
    "did the model return a number", which is the test `scoring.dcf_applicable`
    exists to replace: a REIT's `CFO - CapEx` is positive, so its DCF does not
    error, and the chart drew it a confident bar and a verdict of the same
    visual weight as a valid one — while the Financial Models tab, one tab away,
    suppressed the same number. Passing None keeps the old behaviour for callers
    that cannot classify.
    """
    info = target_fund["info"]
    ranges = []

    if classification is not None and not sector_weights.dcf_applies(classification):
        ranges.append({
            "method": "DCF", "not_applicable": True,
            "reason": f"A discounted-cash-flow valuation does not apply to a "
                      f"{classification.replace('_', ' ')}.",
        })
    elif dcf and not dcf.get("error"):
        band = _dcf_band(dcf)
        if band:
            low, high, basis = band
            ranges.append({"method": f"DCF ({basis})", "low": low, "high": high,
                           "mid": _clamped_mid(dcf.get("fair_value_per_share"), low, high),
                           "independent": dcf.get("assumptions", {}).get("growth_source")
                           != "analyst_consensus_fwd"})

    imp = comps.get("implied_values", {})
    if imp:
        # The envelope is min/max across structurally different multiples, so a
        # single one that does not transfer sets the whole width — the same
        # defect the DCF bar was fixed for. The verdict is taken from the
        # interquartile core instead, and the envelope is kept alongside it so a
        # reader can still see the full spread.
        vals = sorted(imp.values())
        core_low, core_high = (
            (quantiles(vals, n=4)[0], quantiles(vals, n=4)[2]) if len(vals) >= 4
            else (min(vals), max(vals)))
        ranges.append({
            "method": "Peer multiples (implied)",
            "low": round(core_low, 2), "high": round(core_high, 2),
            "mid": round(median(vals), 2),
            "envelope_low": min(vals), "envelope_high": max(vals),
            "peers_used": comps.get("peers_used"),
            # the weakest median behind any multiple actually plotted
            "peers_min": min((( comps.get("peer_medians_n") or {})
                              .get(IMPLIED_TO_MULTIPLE.get(k), 0) for k in imp),
                             default=None),
            "multiples_used": len(vals),
            "suppressed": comps.get("suppressed_multiples") or {},
            "independent": True,
        })

    if info.get("targetLowPrice") and info.get("targetHighPrice"):
        # Context only, never averaged: the reference doc gives analyst targets
        # 0% weight (§5.2), and a target is where the sell-side thinks the price
        # is going rather than an independent valuation of the business. Below
        # four contributing analysts it is not even a range.
        n = info.get("numberOfAnalystOpinions") or 0
        if n >= MIN_ANALYST_OPINIONS:
            low, high = info["targetLowPrice"], info["targetHighPrice"]
            mean = info.get("targetMeanPrice")
            # The width is kept even though the range itself does not vote:
            # disagreement among n informed forecasters is a measure of how
            # uncertain this company's outlook is, which nothing else here
            # captures. Against the mean rather than the price, so it measures
            # the analysts rather than the market's distance from them.
            dispersion = (high - low) / mean if mean else None
            ranges.append({"method": "Analyst targets",
                           "low": low, "high": high, "mid": mean,
                           "context_only": True, "analysts": n,
                           "dispersion": round(dispersion, 4) if dispersion is not None else None,
                           "dispersion_band": None if dispersion is None
                           else "tight" if dispersion < ANALYST_DISPERSION_TIGHT
                           else "moderate" if dispersion < ANALYST_DISPERSION_WIDE else "wide"})

    # A range whose ends coincide is one estimate, not a range. It has to be
    # drawn at a minimum width to be visible at all, so it is flagged here and
    # labelled there rather than passing for a narrow-but-real band.
    for r in ranges:
        if r.get("low") is not None and r["low"] == r["high"]:
            r["degenerate"] = True

    return ranges


def triangulate(ranges: list[dict]) -> dict:
    """Where the methods agree, and how much that agreement is worth.

    The football field's own spec says the point of the chart is the **overlap
    zone** (reference doc §5.2: "the overlap zone is the defensible fair-value
    band"), and the project's quant review endorses the chart only as "the
    intersection of the three methods". Neither existed: the chart drew bars and
    per-method verdicts, so a reader could not distinguish three methods
    agreeing from three methods that happen to straddle the price.

    Analyst targets are excluded from both the overlap and the conviction score.
    The spec gives them 0% weight, and a target range is a forecast of the price
    rather than a valuation of the business — including it would let the thing
    being tested vote on its own test.

    Returns `overlap: None` when the ranges are disjoint. That is not a failure;
    it is the most informative state the chart has, and the one it previously
    could not express.
    """
    scored = [r for r in ranges if not r.get("not_applicable")
              and not r.get("context_only") and r.get("low") is not None]
    mids = [r["mid"] if r.get("mid") is not None else (r["low"] + r["high"]) / 2
            for r in scored]

    analyst = next((r for r in ranges if r.get("context_only")), None)
    out = {
        "methods_scored": [r["method"] for r in scored],
        "overlap": None,
        "conviction": None,
        "midpoint_spread": None,
        "diverged": False,
        "anchors": None,
        # Carried alongside conviction, never inside it: conviction measures
        # whether the *methods* agree, dispersion whether the *forecasters* do.
        # Wide dispersion with tight method agreement is a real and different
        # state from the reverse, and one number cannot say both.
        "analyst_dispersion": (analyst or {}).get("dispersion"),
        "analyst_dispersion_band": (analyst or {}).get("dispersion_band"),
        "analysts": (analyst or {}).get("analysts"),
    }
    if len(scored) < 2:
        # One method is not a triangulation. The intersection of a single range
        # is that range, which would render as an "agreement zone" nothing
        # agreed on — and a conviction grade off one bar is the false precision
        # the spec warns about. A REIT reaches here by design: its DCF row is
        # not applicable, leaving peer multiples alone.
        return out

    low = max(r["low"] for r in scored)
    high = min(r["high"] for r in scored)
    if low <= high:
        out["overlap"] = {"low": round(low, 2), "high": round(high, 2)}

    lo_i, hi_i = mids.index(min(mids)), mids.index(max(mids))
    spread = (mids[hi_i] - mids[lo_i]) / mids[lo_i] if mids[lo_i] else None
    if spread is None:
        return out
    out["midpoint_spread"] = round(spread, 4)
    out["conviction"] = ("HIGH" if spread <= CONVICTION_HIGH
                         else "MEDIUM" if spread <= CONVICTION_MEDIUM else "LOW")
    out["diverged"] = spread > DIVERGENCE_CALLOUT
    out["anchors"] = {
        "low_method": scored[lo_i]["method"], "low_mid": round(mids[lo_i], 2),
        "high_method": scored[hi_i]["method"], "high_mid": round(mids[hi_i], 2),
    }
    return out


def price_gap_bridge(dcf: dict, price: float | None) -> dict | None:
    """The distance from the DCF to the price, decomposed into named steps.

    Measured across eleven names, the conviction grade came out LOW every time
    and the overlap zone was non-empty once. A grade that never varies carries
    no information, however correctly it is computed — so the chart stopped
    leading with it. What a reader actually needs is not a letter but the
    arithmetic: here is our number, here is what the one adjustment we can
    justify does to it, here is the price, and here is what remains.

    The residual is the point. It is labelled as unexplained rather than
    absorbed into a fudge, because it is not a modelling error — it is the
    market pricing a longer competitive-advantage period, a lower discount rate
    or a higher terminal cash conversion than a ten-year fade at 2.5% can
    express. Naming the size of that bet is the honest output. Closing it by
    tuning the model would make the DCF an expensive way to display the price.

    Only the base-year step appears, because it is the only adjustment the
    platform can compute from filed data today. Rows for non-operating assets or
    for the interest-income double-count are deliberately absent rather than
    stubbed at zero: an empty line implies a check was run.
    """
    if dcf.get("error"):
        return None
    fair_value = dcf.get("fair_value_per_share")
    if not fair_value or not price:
        return None

    steps = [{"label": "Our DCF fair value, on the reported base year",
              "value": fair_value, "kind": "start"}]
    adjusted = fair_value

    base_year = (dcf.get("diagnostics") or {}).get("base_year") or {}
    normalised = base_year.get("fair_value_normalised")
    # `> 0` rather than `is not None`: a normalised enterprise value below net
    # debt gives a negative adjusted figure, and every percentage measured
    # against it afterwards is nonsense — "the market is 340% above a value of
    # -12". A leveraged company whose newest year ran above its own average can
    # reach that. The step is dropped rather than shown, since the bridge would
    # otherwise end in a number the reader cannot interpret.
    if normalised is not None and normalised > 0 and base_year.get("ratio_to_mean"):
        steps.append({
            "label": (f"If the base year ran at this company's own "
                      f"{base_year['periods']}-year average margin "
                      f"({base_year['ratio_to_mean']}x today)"),
            "value": round(normalised - fair_value, 2),
            "kind": "adjustment",
        })
        adjusted = normalised

    residual = round(price - adjusted, 2)
    return {
        "steps": steps,
        "adjusted": round(adjusted, 2),
        "price": price,
        "residual": residual,
        # Against the adjusted value, not against the price: the question is how
        # far our number would have to move, not how far the market's would.
        "residual_pct": round((price / adjusted - 1) * 100, 1) if adjusted else None,
        "residual_direction": "market_above" if residual > 0 else "market_below",
    }


def reconciling_growth(target_fund: dict, target_value: float,
                       peers: list[dict] | None = None) -> float | None:
    """The growth rate at which the DCF would agree with `target_value`.

    This is the answer to "the methods disagree, now what". The reference doc
    forbids averaging two anchors that diverge (§5.2: "do not average into false
    precision — report both anchors and the assumption that separates them"),
    and the project's own quant review ranks back-solving the DCF's assumptions
    as the single most valuable thing the platform does. Naming the growth rate
    that reconciles the two turns an unanswerable question — which bar do I
    believe — into one the reader can actually research.

    Measured live 2026-08-12 on 0700.HK: the DCF's 682.40 sits 52.7% above the
    peer-multiple core, the model is compounding at 9.38% taken from analyst
    consensus, and the two methods meet at roughly 4%.

    None means the target lies outside what any rate in the model's own
    validity range can produce, which is itself worth saying.

    The bisection lives in `financial_models.solve_for_fair_value`, shared with
    the price reconciliation that back-solves the same model against the market
    rather than against the peers.
    """
    return fm.solve_for_fair_value(
        target_fund, target_value, "growth_rate",
        fm.GROWTH_VALIDITY_RANGE[0], fm.GROWTH_VALIDITY_RANGE[1], peers, rising=True)
