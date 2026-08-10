/**
 * The regression these tests exist for: markers were grouped by the bar's
 * GMT+8-shifted date while `e.date` arrives as a UTC date, so on a US intraday
 * chart an event dated D landed three hours into session D-1. Nothing about the
 * rendered chart looked wrong — a misplaced dot is still a dot — which is
 * exactly why it needs a test rather than an eyeball.
 */
import { describe, it, expect } from 'vitest';
import { eventStamp, groupEventsByBar, toDateStr } from './events';
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

describe('groupEventsByBar — intraday placement from a timestamp', () => {
  // US session, hourly bars opening 13:30 UTC. Bar N covers [N, N+1h).
  const { bars, opens } = intradayBars(13, [6]);
  const at = (h, m) => utc(2026, 8, 6, h, m);

  it('places a story on the bar it happened during, not the next one', () => {
    const [group] = groupEventsByBar(bars, [ev('2026-08-06', { published_at: at(14, 5) })]);

    // 14:05 falls inside the 13:30 bar, so the reader sees the reaction that
    // followed rather than a dot sitting after it.
    expect(group.time).toBe(opens[6]);
  });

  it('separates two stories that fall in different bars', () => {
    const groups = groupEventsByBar(bars, [
      ev('2026-08-06', { published_at: at(14, 5), title: 'early' }),
      ev('2026-08-06', { published_at: at(17, 45), title: 'late' }),
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[0].items[0].title).toBe('early');
    expect(groups[1].time).toBe(opens[6] + 4 * 3600); // the 17:30 bar
  });

  it('keeps stories inside one bar clustered together', () => {
    const groups = groupEventsByBar(bars, [
      ev('2026-08-06', { published_at: at(14, 5) }),
      ev('2026-08-06', { published_at: at(14, 20) }),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].items).toHaveLength(2);
  });

  it('emits groups in ascending bar order regardless of input order', () => {
    const groups = groupEventsByBar(bars, [
      ev('2026-08-06', { published_at: at(18, 0) }),
      ev('2026-08-06', { published_at: at(14, 5) }),
    ]);

    expect(groups.map((g) => g.time)).toEqual([...groups.map((g) => g.time)].sort((a, b) => a - b));
  });

  it('moves after-hours news to the next session rather than the previous close', () => {
    const two = intradayBars(13, [6, 7]);
    // 23:00 UTC on the 6th: after the 20:30 close, no bar contains it.
    const [group] = groupEventsByBar(two.bars, [
      ev('2026-08-06', { published_at: utc(2026, 8, 6, 23, 0) }),
    ]);

    expect(group.time).toBe(two.opens[7]);
  });

  it('moves news published shortly after the close to the next session', () => {
    // 20:45 UTC is 1h15 past the 19:30 close — inside the mean gap between bars
    // (~2h20, dragged up by the overnight jump) but outside the median (1h).
    // Only the median reads this as "after the close" and moves it forward, so
    // this is the case that distinguishes the two.
    const two = intradayBars(13, [6, 7]);
    const [group] = groupEventsByBar(two.bars, [
      ev('2026-08-06', { published_at: utc(2026, 8, 6, 20, 45) }),
    ]);

    expect(group.time).toBe(two.opens[7]);
  });

  it('ignores the timestamp on daily bars, where it cannot be expressed', () => {
    const daily = ['2026-08-06', '2026-08-07'].map((d) => ({ time: d }));
    const [group] = groupEventsByBar(daily, [
      ev('2026-08-07', { published_at: utc(2026, 8, 7, 17, 45) }),
    ]);

    expect(group.time).toBe('2026-08-07');
  });

  it('falls back to the date when an event carries no timestamp', () => {
    // SEC filings never carry one — they must still land on the session open.
    const [group] = groupEventsByBar(bars, [ev('2026-08-06')]);

    expect(group.time).toBe(opens[6]);
  });

  it('drops a timestamped story that predates the chart window', () => {
    expect(groupEventsByBar(bars, [
      ev('2026-08-06', { published_at: utc(2026, 7, 1, 14, 0) }),
    ])).toEqual([]);
  });

  it('clamps a timestamped story from after the last bar onto the last bar', () => {
    const groups = groupEventsByBar(bars, [
      ev('2026-08-06', { published_at: utc(2026, 8, 20, 14, 0) }),
    ]);

    expect(groups[0].time).toBe(bars[bars.length - 1].time);
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

describe('eventStamp — the two precisions must be distinguishable', () => {
  it('shows the publish time, in chart timezone, for a timestamped story', () => {
    // 14:05 UTC renders as 22:05 GMT+8, matching the axis the dot sits on.
    const stamp = eventStamp({ date: '2026-08-06', published_at: utc(2026, 8, 6, 14, 5) });

    expect(stamp.text).toBe('2026-08-06 22:05');
    expect(stamp.title).toMatch(/not necessarily when the market learned/);
  });

  it('marks a date-only event rather than implying it broke at the open', () => {
    const stamp = eventStamp({ date: '2026-08-06' });

    expect(stamp.text).toBe('2026-08-06 · day only');
    expect(stamp.title).toMatch(/session open/);
  });

  it('treats a null timestamp as day-only, not as epoch zero', () => {
    expect(eventStamp({ date: '2026-08-06', published_at: null }).text)
      .toBe('2026-08-06 · day only');
  });
});
