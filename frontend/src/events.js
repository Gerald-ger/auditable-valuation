/**
 * Snapping chart events (news, SEC filings) onto price bars.
 *
 * Extracted from PriceChart so it can be tested: this is pure logic over two
 * arrays, and the timezone half of it is the kind that breaks silently and
 * invisibly — a marker three hours into the wrong session still looks like a
 * marker.
 */
import { DISPLAY_TZ_LABEL, fromChartTime, toChartTime } from './charttime';

/** Bar time -> YYYY-MM-DD. Handles epochs, date strings and BusinessDay objects. */
export const toDateStr = (t) => {
  if (typeof t === 'string') return t;
  if (typeof t === 'number') return new Date(t * 1000).toISOString().slice(0, 10);
  return `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`;
};

/**
 * Attach every event to a bar, chronologically.
 *
 * Events are matched to the next trading day on or after their date, not to an
 * exact date match — a Saturday filing used to produce no dot at all because no
 * bar carried that date. Events dated after the last bar (today's news against
 * yesterday's close) clamp onto the final bar rather than vanishing.
 *
 * Matching happens in **true UTC**, display stays in **chart space**. Bars
 * arrive already shifted to GMT+8 (see charttime.js), but `e.date` is a UTC
 * date from the backend, and a US session straddles midnight once shifted:
 * 09:30-16:00 ET renders as 21:30 on the session's date through 04:00 the
 * following one. Grouping on the shifted date therefore mapped the second
 * calendar date onto a bar *mid-way through the previous session*, putting an
 * event dated D three hours into session D-1. Unshifting for the match fixes
 * that; every US and HK session sits inside a single UTC date, so one date
 * means one session for both markets.
 *
 * `date` on the returned group is still the resolved bar's *chart-space* date,
 * so the axis label, the marker's popup header and the hover legend continue to
 * agree — which is why the grouping could not simply be moved to UTC wholesale.
 */
export function groupEventsByBar(bars, events) {
  if (!bars.length) return [];
  const dates = [];
  const indexOfDate = new Map();
  for (let i = 0; i < bars.length; i++) {
    const d = toDateStr(fromChartTime(bars[i].time));
    if (!indexOfDate.has(d)) {
      indexOfDate.set(d, i);
      dates.push(d);
    }
  }
  const first = dates[0];
  const last = dates[dates.length - 1];
  const intraday = typeof bars[0].time === 'number';
  const span = intraday ? medianBarSpan(bars) : 0;

  /** Index of the bar an event belongs on, or null to drop it. */
  const resolve = (e) => {
    // A timestamped story on an intraday chart goes on the bar it happened
    // during, which is the whole point: the reader sees the move that followed.
    // Only news carries one — SEC filings expose a date, so they fall through.
    if (intraday && typeof e.published_at === 'number') {
      const t = toChartTime(e.published_at);
      if (t < bars[0].time) return null; // predates the chart window
      let lo = 0;
      let hi = bars.length - 1;
      let idx = 0;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (bars[mid].time <= t) {
          idx = mid;
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      // Past the end of that bar means it landed in a gap — after the close, or
      // over a weekend — where no bar contains it. Those move to the next bar,
      // the first session that could react, matching the date rule below.
      const inGap = t - bars[idx].time >= span;
      return inGap ? Math.min(idx + 1, bars.length - 1) : idx;
    }

    if (!e.date || e.date < first) return null;
    let idx = dates.length - 1;
    if (e.date <= last) {
      let lo = 0;
      let hi = dates.length - 1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (dates[mid] >= e.date) {
          idx = mid;
          hi = mid - 1;
        } else {
          lo = mid + 1;
        }
      }
    }
    return indexOfDate.get(dates[idx]);
  };

  const byIndex = new Map();
  for (const e of events) {
    const idx = resolve(e);
    if (idx == null) continue;
    if (!byIndex.has(idx)) byIndex.set(idx, []);
    byIndex.get(idx).push(e);
  }

  // ascending bar order — lightweight-charts requires ascending marker times
  const groups = [];
  for (const idx of [...byIndex.keys()].sort((a, b) => a - b)) {
    const time = bars[idx].time;
    groups.push({ date: toDateStr(time), time, items: byIndex.get(idx) });
  }
  return groups;
}

/**
 * How one event's timing should read in the popup.
 *
 * Two precisions share the chart — news carries a publish time, SEC filings a
 * date — and the dots look identical. Saying which is which here is the whole
 * mechanism for that, so a reader never assumes a marker at the session open
 * means the story broke at the open.
 *
 * The time is the *publisher's*, not the moment the market learned: wire delay,
 * aggregation and republication all sit in between. `title` says so rather than
 * letting a minute-precise label imply more than the feed supports.
 */
export function eventStamp(e) {
  if (typeof e.published_at !== 'number') {
    return {
      text: `${e.date} · day only`,
      title: 'This source reports a date but no time, so the marker sits on the session open.',
    };
  }
  const iso = new Date(toChartTime(e.published_at) * 1000).toISOString();
  return {
    text: `${iso.slice(0, 10)} ${iso.slice(11, 16)}`,
    title: `Publisher timestamp, ${DISPLAY_TZ_LABEL}. When the story was filed, `
      + 'not necessarily when the market learned.',
  };
}

/**
 * Typical spacing between consecutive bars, used to tell "inside this bar" from
 * "in the gap after it".
 *
 * The median rather than the mean: a session contributes many intraday gaps and
 * exactly one overnight gap, so the median is the intraday spacing while the
 * mean would be dragged upwards by the overnight jumps and by weekends.
 */
function medianBarSpan(bars) {
  if (bars.length < 2) return Infinity;
  const spans = [];
  for (let i = 1; i < bars.length; i++) spans.push(bars[i].time - bars[i - 1].time);
  spans.sort((a, b) => a - b);
  return spans[spans.length >> 1];
}
