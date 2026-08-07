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
