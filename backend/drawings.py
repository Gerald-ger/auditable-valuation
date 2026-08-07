"""Geometry of user-drawn chart lines — computed here, never by the model.

A drawing is a **user assertion**, not a measurement: the app did not decide that
$210 is support, the reader did. That distinction has to survive into the AI
context, or the model will discuss a level as though the engine derived it.

So this module does what the rest of the backend does with numbers: it computes
the facts deterministically — where the line sits today, how far price is from
it, how often price actually respected it — and the AI is given those facts plus
an explicit note about who drew them. Same rule as everywhere else in this app:
the model comments, it does not calculate.

Coordinates are true UTC epochs. The chart displays GMT+8 and converts at its
own boundary; nothing here knows or cares about the display timezone.
"""
from __future__ import annotations

# A touch is a bar whose extreme came within this fraction of the line. 0.5% is
# tight enough that a line through empty space scores zero and loose enough that
# a real reaction still registers on a normal-volatility equity.
TOUCH_TOLERANCE = 0.005
SECONDS_PER_DAY = 86400


def price_at(drawing: dict, when: int | None) -> float | None:
    """Price of the line at time `when`, extending the segment indefinitely.

    A horizontal line is flat by definition. A trendline is extrapolated beyond
    its drawn endpoints, because the reason to draw one is to ask where it will
    be — refusing to extend it would make the line useless the moment price
    moved past the second point.
    """
    if drawing["kind"] == "hline":
        return drawing["p1"]
    t1, t2 = drawing.get("t1"), drawing.get("t2")
    p1, p2 = drawing.get("p1"), drawing.get("p2")
    if None in (t1, t2, p1, p2) or when is None or t2 == t1:
        return None
    return p1 + (p2 - p1) * (when - t1) / (t2 - t1)


def slope_per_day(drawing: dict) -> float | None:
    if drawing["kind"] == "hline":
        return 0.0
    t1, t2 = drawing.get("t1"), drawing.get("t2")
    p1, p2 = drawing.get("p1"), drawing.get("p2")
    if None in (t1, t2, p1, p2) or t2 == t1:
        return None
    return (p2 - p1) / ((t2 - t1) / SECONDS_PER_DAY)


def _bar_epoch(bar: dict) -> int | None:
    """Bars carry an epoch when intraday and a date string when daily."""
    t = bar.get("time")
    if isinstance(t, (int, float)):
        return int(t)
    if isinstance(t, str):
        from datetime import datetime, timezone
        try:
            return int(datetime.strptime(t[:10], "%Y-%m-%d")
                       .replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return None
    return None


def describe(drawing: dict, bars: list[dict], current_price: float | None) -> dict:
    """One drawing reduced to stated facts.

    `touches` counts bars whose high or low came within TOUCH_TOLERANCE of the
    line — the closest thing to evidence that a drawn level meant anything.
    A line with zero touches is reported as zero rather than omitted: "you drew
    this and price never respected it" is the most useful thing to say about it.
    """
    epochs = [(_bar_epoch(b), b) for b in bars]
    epochs = [(e, b) for e, b in epochs if e is not None]

    touches, breaks_above, breaks_below = 0, 0, 0
    for epoch, bar in epochs:
        line = price_at(drawing, epoch)
        if line is None or line <= 0:
            continue
        high, low = bar.get("high"), bar.get("low")
        close = bar.get("close")
        if high is not None and low is not None:
            if abs(high - line) / line <= TOUCH_TOLERANCE or \
               abs(low - line) / line <= TOUCH_TOLERANCE:
                touches += 1
        if close is not None:
            if close > line * (1 + TOUCH_TOLERANCE):
                breaks_above += 1
            elif close < line * (1 - TOUCH_TOLERANCE):
                breaks_below += 1

    latest_epoch = epochs[-1][0] if epochs else None
    line_now = price_at(drawing, latest_epoch)
    distance_pct = None
    if line_now and current_price:
        distance_pct = round((current_price / line_now - 1) * 100, 2)

    return {
        "id": drawing.get("id"),
        "kind": drawing["kind"],
        "label": drawing.get("label"),
        "drawn_by": "user",  # never let the model read this as a computed level
        "price_at_start": drawing.get("p1"),
        "price_at_end": drawing.get("p2"),
        "line_price_now": round(line_now, 4) if line_now is not None else None,
        "slope_per_day": (lambda s: round(s, 4) if s is not None else None)(
            slope_per_day(drawing)),
        "current_price": current_price,
        "price_vs_line_pct": distance_pct,
        "price_is": None if distance_pct is None else (
            "above" if distance_pct > 0 else "below" if distance_pct < 0 else "at"),
        "bars_touching": touches,
        "bars_closing_above": breaks_above,
        "bars_closing_below": breaks_below,
        "touch_tolerance_pct": TOUCH_TOLERANCE * 100,
    }


def describe_all(drawings: list[dict], bars: list[dict],
                 current_price: float | None) -> dict:
    """The block handed to the AI. Empty is stated, not omitted."""
    described = [describe(d, bars, current_price) for d in drawings]
    return {
        "count": len(described),
        "drawings": described,
        "note": ("These lines were drawn by the user on the price chart, not "
                 "derived by the analysis engine. Their geometry below is "
                 "computed; whether they mark anything real is exactly what the "
                 "user is asking about. Do not present them as model output, and "
                 "do not restate a price the engine did not provide."),
    }
