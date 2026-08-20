/**
 * Display timezone.
 *
 * The backend returns true UTC epochs; lightweight-charts renders an epoch as
 * UTC and offers no timezone setting, so a US 09:30 open drew as 13:30 and a
 * Hong Kong 09:30 open drew as 01:30 — neither the exchange's clock nor the
 * reader's. Shifting the timestamp on the way into the chart is the library's
 * documented idiom for this.
 *
 * GMT+8 is one clock for every market: HK reads naturally, and a US session
 * reads 21:30–03:58, which is when a Hong Kong reader would actually be
 * watching it. The cost is that a US trading day straddles midnight and so
 * spans two calendar dates on the chart — inherent to the choice, not a bug.
 *
 * Only intraday bars carry a time. Daily and weekly bars are date strings and
 * pass through untouched, which is right: a US daily bar dated 2026-08-06 is
 * that session, not a moment to be shifted.
 */
export const DISPLAY_TZ_OFFSET_S = 8 * 3600;
export const DISPLAY_TZ_LABEL = 'GMT+8';

/** True epoch -> chart space. Identity for date-string (daily/weekly) bars. */
export const toChartTime = (t) =>
  typeof t === 'number' ? t + DISPLAY_TZ_OFFSET_S : t;
/** Chart space -> true epoch, for anything leaving the chart (e.g. drawings). */
export const fromChartTime = (t) =>
  typeof t === 'number' ? t - DISPLAY_TZ_OFFSET_S : t;

/**
 * Chart time -> the integer UTC epoch a drawing is **stored** as.
 *
 * `fromChartTime` above cannot do this and should not: it passes a date string
 * through untouched, which is correct for a bar (a daily bar dated 2026-08-06
 * *is* that session, not a moment) and wrong for a drawing, because the API
 * declares `t1`/`t2` as integers and `backend/drawings.py` does arithmetic on
 * them to project a line forward.
 *
 * That gap made trendlines impossible to save on every daily-or-coarser range —
 * `coordinateToTime` returns a date string there, the POST carried it, and the
 * API answered **422 `int_parsing`**, which `post(...).catch(() => {})` then
 * swallowed. Confirmed against the running backend on 2026-08-20; the failure
 * was silent and total, and it predates the drawing work of that day.
 *
 * Three inputs, because lightweight-charts uses three representations: a
 * timestamp for intraday bars (shifted, so the display offset comes back off), a
 * date string for daily and coarser, and a `{year, month, day}` business day,
 * which `coordinateToTime` can return even for a string series.
 */
export function drawingEpoch(t) {
  if (t == null) return null;
  if (typeof t === 'number') return Math.round(t - DISPLAY_TZ_OFFSET_S);
  if (typeof t === 'string') {
    const ms = Date.parse(t);
    return Number.isFinite(ms) ? Math.round(ms / 1000) : null;
  }
  if (typeof t === 'object' && t.year != null) {
    return Math.round(Date.UTC(t.year, (t.month ?? 1) - 1, t.day ?? 1) / 1000);
  }
  return null;
}

/**
 * A stored epoch -> chart time in the representation **this series** uses.
 *
 * The other half of the same problem. A drawing is stored as one number, but a
 * chart addresses its x-axis in whatever type its bars carry, so handing a
 * daily series an epoch places the line nowhere — `timeToCoordinate` cannot
 * match it against date strings. `intraday` is read from the bars themselves
 * rather than from the interval string, so it follows the data.
 *
 * Converting here, at render, rather than once at load is what makes a drawing
 * survive a change of period: the same stored epoch becomes a timestamp on the
 * 5-day chart and `2026-08-06` on the yearly one.
 */
export function drawingChartTime(epoch, intraday) {
  if (typeof epoch !== 'number') return epoch ?? null;
  if (intraday) return epoch + DISPLAY_TZ_OFFSET_S;
  return new Date(epoch * 1000).toISOString().slice(0, 10);
}
