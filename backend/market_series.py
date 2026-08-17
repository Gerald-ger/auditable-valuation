"""Return-series maths: beta by regression, and performance over a window.

Pure functions over the bar lists `data_provider.get_history` returns. Nothing
here fetches, so the valuation layer keeps the property `financial_models`
already documents — network resolved by the caller, injected as an argument,
model offline-testable.

Why this module exists at all: the platform was reading *scalars* from the
vendor where the honest answer needs a *series*. `info["beta"]` is a number
someone else computed by an undisclosed method, and it is measurably wrong for
whole sectors — XOM's own 0.173, and its four peers at 0.488, 0.123, -0.218,
-0.212. `52WeekChange` is worse: measured live 2026-08-14, `^GSPC` reported it
in percent (20.918) while `^HSI` reported it in decimal (0.500), and the HSI
figure matched neither its own price history (-1.41%) nor any unit reading of
it. Series can be checked; scalars have to be trusted.
"""
from __future__ import annotations

import math

# Two-sided 95% normal quantile for the beta interval. Normal rather than
# Student's t because the sample is never small by construction — the minimum
# below is 104 observations, where t is 1.983 against 1.960, a difference far
# inside the noise the interval is describing.
BETA_CI_Z = 1.96

# Weekly bars, so 104 is two years. Below this a regression is fitting noise:
# a newly listed company has no cycle in it, and the standard beta windows are
# two to five years precisely because shorter ones are unstable. Falling short
# is not an error — the caller drops to the peer/reported ladder instead.
MIN_BETA_OBSERVATIONS = 104

# Weekly bars again: 52 periods back is one year, and the metric is named for it.
RELATIVE_STRENGTH_PERIODS = 52


def align(stock_bars: list[dict], index_bars: list[dict]) -> tuple[list[float], list[float]]:
    """Closes for the dates both series actually have, oldest first.

    An inner join rather than a zip. Hong Kong and US calendars differ — their
    holidays do not coincide and even weekly bars land on different stamps
    across markets (measured on the committed fixtures: AAPL and ^GSPC share
    all 262 rows, 0700.HK and ^HSI share all 261, but AAPL against ^HSI misses
    one). Zipping two lists of *nearly* equal length would silently pair each
    return with its neighbour from the other market from the mismatch onward,
    which is a plausible-looking beta computed from misaligned weeks.

    Aligning closes and differencing afterwards, rather than differencing first
    and aligning the returns, is deliberate: after the join both series sit on
    one date grid, so every matched return spans the same interval. Aligning
    pre-computed returns would pair a one-week move against a two-week one
    wherever a date was dropped.

    Non-positive closes are dropped here, on both sides, rather than guarded
    inside `returns`: filtering during the differencing would shorten one list
    and not the other, and two return series of different lengths pair week 40
    of one against week 41 of the other for the rest of the sample. Dropping the
    date from the join keeps the two outputs the same length by construction.
    Order is the input order — `get_history` returns bars oldest-first, and
    returns are only meaningful chronologically.
    """
    index_closes = {b["time"]: b["close"] for b in index_bars
                    if b.get("close") and b["close"] > 0}
    pairs = [(b["close"], index_closes[b["time"]])
             for b in stock_bars
             if b.get("close") and b["close"] > 0 and b["time"] in index_closes]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def returns(closes: list[float]) -> list[float]:
    """Period-over-period fractional returns. Assumes positive closes, which is
    what `align` guarantees for the pair it returns."""
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def beta_fit(stock_bars: list[dict], index_bars: list[dict]) -> tuple[dict | None, int]:
    """(fit, observations) — the regression *and* how well it fits.

    `fit` is None on the same two conditions `beta` returns None for; otherwise
    it carries `beta`, `standard_error`, `r_squared` and `confidence_interval`.

    Why the fit statistics are not optional extras. A slope alone cannot say
    whether it measured anything, and on the committed fixtures the difference
    is not academic: 0700.HK regresses at 1.319 with an R^2 of 0.691, while XOM
    regresses at 0.289 with an R^2 of **0.028** — the index explains under 3% of
    its variance, and its 95% interval [0.08, 0.49] is wide enough to move that
    company's fair value from 123 to 228. Both used to arrive at the caller as
    a bare four-decimal number with nothing to separate them.

    The standard error is the textbook OLS slope error,
    `sqrt(SSE / (n - 2) / Sxx)`. Sxx is the `variance` accumulator below, which
    is already the un-normalised sum of squared index deviations, so the error
    costs one extra pass and no new dependency. Cross-checked when written
    against numpy's own `polyfit(..., cov=True)` covariance matrix and against
    the algebraic form, agreeing to 1e-12 on all seven fixtures, and the
    identity `t^2 = R^2/(1-R^2) * (n-2)` holds exactly.
    """
    rs, ri = (returns(s) for s in align(stock_bars, index_bars))
    n = min(len(rs), len(ri))
    if n < MIN_BETA_OBSERVATIONS:
        return None, n

    mean_s, mean_i = sum(rs) / n, sum(ri) / n
    # The 1/(n-1) in both covariance and variance cancels, so it is left out
    # rather than written twice and divided away.
    covariance = sum((rs[k] - mean_s) * (ri[k] - mean_i) for k in range(n))
    variance = sum((ri[k] - mean_i) ** 2 for k in range(n))
    if variance == 0:
        return None, n

    slope = covariance / variance
    intercept = mean_s - slope * mean_i
    sse = sum((rs[k] - (intercept + slope * ri[k])) ** 2 for k in range(n))
    total = sum((rs[k] - mean_s) ** 2 for k in range(n))
    standard_error = math.sqrt(sse / (n - 2) / variance)
    half = BETA_CI_Z * standard_error
    return {
        "beta": slope,
        "standard_error": standard_error,
        # None rather than 0.0 for a motionless *stock*: nothing was explained
        # because there was nothing to explain, which is not the same as a
        # regression that failed to explain a real series.
        "r_squared": None if total == 0 else 1 - sse / total,
        "confidence_interval": (slope - half, slope + half),
    }, n


def beta(stock_bars: list[dict], index_bars: list[dict]) -> tuple[float | None, int]:
    """(beta, observations) — cov(stock, index) / var(index).

    Returns `(None, n)` when there is not enough overlap or the index did not
    move at all, so the caller can fall through to its other sources and report
    which one it used. The variance guard is not theoretical: a constant series
    is what a placeholder or a halted market looks like.

    A thin reading of `beta_fit`, so the value and the statistics describing it
    can never be computed two different ways.
    """
    fit, n = beta_fit(stock_bars, index_bars)
    return (fit["beta"] if fit else None), n


def change_over(bars: list[dict], periods: int = RELATIVE_STRENGTH_PERIODS) -> float | None:
    """Fractional change across the trailing `periods` bars, or None.

    Measured on the bars themselves rather than read from the vendor's
    `52WeekChange`, which is the field this exists to stop trusting.
    """
    closes = [b["close"] for b in bars if b.get("close")]
    if len(closes) < periods + 1:
        return None
    first, last = closes[-(periods + 1)], closes[-1]
    return last / first - 1 if first > 0 else None
