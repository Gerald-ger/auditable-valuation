/**
 * The regression these tests exist for: markers were grouped by the bar's
 * GMT+8-shifted date while `e.date` arrives as a UTC date, so on a US intraday
 * chart an event dated D landed three hours into session D-1. Nothing about the
 * rendered chart looked wrong — a misplaced dot is still a dot — which is
 * exactly why it needs a test rather than an eyeball.
 */
import { describe, it, expect } from 'vitest';
import { groupEventsByBar, toDateStr } from './events';
import { DISPLAY_TZ_OFFSET_S } from './charttime';

const utc = (y, m, d, hh, mm) => Date.UTC(y, m - 1, d, hh, mm) / 1000;

/** Hourly bars for `days`, in chart space, opening at `openUtcHour` UTC. */
function intradayBars(openUtcHour, days) {
  const bars = [];
  const opens = {};
  for (const d of days) {
    for (let h = openUtcHour; h < openUtcHour + 7; h++) {
      const trueTime = utc(2026, 8, d, h, 30);
      if (h === openUtcHour) opens[d] = trueTime + DISPLAY_TZ_OFFSET_S;
      bars.push({ time: trueTime + DISPLAY_TZ_OFFSET_S });
    }
  }
  return { bars, opens };
}

const ev = (date, extra = {}) => ({ date, category: 'company', title: date, ...extra });

describe('groupEventsByBar — session placement', () => {
  it('puts a US intraday event on its own session open, not the previous one', () => {
    // 09:30-16:00 ET == 13:30-20:00 UTC. Shifted +8h this session spans two
    // calendar dates, which is what used to break the match.
    const { bars, opens } = intradayBars(13, [6, 7]);
    const groups = groupEventsByBar(bars, [ev('2026-08-06'), ev('2026-08-07')]);

    expect(groups).toHaveLength(2);
    expect(groups[0].time).toBe(opens[6]);
    expect(groups[1].time).toBe(opens[7]); // was 3h into session 08-06
  });

  it('puts an HK intraday event on its own session open', () => {
    // 09:30-16:00 HKT == 01:30-08:00 UTC — inside one UTC date either way, so
    // this case was already correct and must stay that way.
    const { bars, opens } = intradayBars(1, [6, 7]);
    const groups = groupEventsByBar(bars, [ev('2026-08-06'), ev('2026-08-07')]);

    expect(groups.map((g) => g.time)).toEqual([opens[6], opens[7]]);
  });

  it('leaves daily bars, which carry date strings, untouched', () => {
    const bars = ['2026-08-06', '2026-08-07'].map((d) => ({ time: d }));
    const groups = groupEventsByBar(bars, [ev('2026-08-06'), ev('2026-08-07')]);

    expect(groups.map((g) => g.time)).toEqual(['2026-08-06', '2026-08-07']);
  });
});

describe('groupEventsByBar — display date stays in chart space', () => {
  it('reports the resolved bar chart-space date, so axis and popup agree', () => {
    const { bars, opens } = intradayBars(13, [6]);
    const [group] = groupEventsByBar(bars, [ev('2026-08-06')]);

    expect(group.time).toBe(opens[6]);
    expect(group.date).toBe(toDateStr(group.time));
  });
});

describe('groupEventsByBar — existing conventions preserved', () => {
  it('snaps a non-trading-day event onto the next trading bar', () => {
    const bars = ['2026-08-07', '2026-08-10'].map((d) => ({ time: d })); // Fri, Mon
    const [group] = groupEventsByBar(bars, [ev('2026-08-08')]); // Saturday

    expect(group.time).toBe('2026-08-10');
  });

  it('clamps an event dated after the last bar onto the last bar', () => {
    const bars = ['2026-08-06', '2026-08-07'].map((d) => ({ time: d }));
    const [group] = groupEventsByBar(bars, [ev('2026-08-20')]);

    expect(group.time).toBe('2026-08-07');
  });

  it('drops an event predating the chart window', () => {
    const bars = ['2026-08-06'].map((d) => ({ time: d }));

    expect(groupEventsByBar(bars, [ev('2026-07-01')])).toEqual([]);
  });

  it('collects several events onto one bar and emits ascending times', () => {
    const bars = ['2026-08-06', '2026-08-07'].map((d) => ({ time: d }));
    const groups = groupEventsByBar(bars, [
      ev('2026-08-07'), ev('2026-08-06'), ev('2026-08-07'),
    ]);

    expect(groups.map((g) => g.time)).toEqual(['2026-08-06', '2026-08-07']);
    expect(groups[1].items).toHaveLength(2);
  });

  it('returns nothing when there are no bars', () => {
    expect(groupEventsByBar([], [ev('2026-08-06')])).toEqual([]);
  });
});
