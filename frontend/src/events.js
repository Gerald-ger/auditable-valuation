/**
 * Snapping chart events (news, SEC filings) onto price bars.
 *
 * Extracted from PriceChart so it can be tested: this is pure logic over two
 * arrays, and the timezone half of it is the kind that breaks silently and
 * invisibly — a marker three hours into the wrong session still looks like a
 * marker.
 */
import { fromChartTime } from './charttime';

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
  const timeOfDate = new Map();
  for (const b of bars) {
    const d = toDateStr(fromChartTime(b.time));
    if (!timeOfDate.has(d)) {
      timeOfDate.set(d, b.time);
      dates.push(d);
    }
  }
  const first = dates[0];
  const last = dates[dates.length - 1];

  const byDate = new Map();
  for (const e of events) {
    if (!e.date || e.date < first) continue; // predates the chart window
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
    const key = dates[idx];
    if (!byDate.has(key)) byDate.set(key, []);
    byDate.get(key).push(e);
  }

  // emit in `dates` order — lightweight-charts requires ascending marker times
  const groups = [];
  for (const d of dates) {
    const items = byDate.get(d);
    const time = timeOfDate.get(d);
    if (items) groups.push({ date: toDateStr(time), time, items });
  }
  return groups;
}
