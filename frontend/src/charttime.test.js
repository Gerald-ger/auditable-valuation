/**
 * The regression these tests guard against: drawings are persisted as true UTC
 * epochs and rendered in chart space, so `toChartTime` and `fromChartTime` sit on
 * a save/load boundary. If they ever stop being exact inverses, every stored
 * trendline walks eight hours further from the bar it was drawn on with each
 * round trip — a drift that looks like a line nobody moved.
 *
 * The string cases matter as much as the numeric ones. Daily and weekly bars
 * arrive as date strings and must pass through untouched: shifting `2026-08-06`
 * would be shifting a whole session, not a moment inside one.
 */
import { describe, it, expect } from 'vitest';
import {
  DISPLAY_TZ_OFFSET_S,
  DISPLAY_TZ_LABEL,
  toChartTime,
  fromChartTime,
  drawingEpoch,
  drawingChartTime,
} from './charttime';

const EPOCH = Date.UTC(2026, 7, 6, 13, 30) / 1000; // a US session open, in UTC

describe('the display timezone constants', () => {
  it('is GMT+8', () => {
    expect(DISPLAY_TZ_OFFSET_S).toBe(8 * 3600);
  });

  it('carries a label that agrees with the offset it advertises', () => {
    // The label is printed beside times the offset produced. A mismatch is not
    // a rendering bug, it is a caption asserting the wrong clock.
    expect(DISPLAY_TZ_LABEL).toBe(`GMT+${DISPLAY_TZ_OFFSET_S / 3600}`);
  });
});

describe('toChartTime', () => {
  it('shifts a numeric epoch forward by the display offset', () => {
    expect(toChartTime(EPOCH)).toBe(EPOCH + DISPLAY_TZ_OFFSET_S);
  });

  it('leaves a date string untouched', () => {
    expect(toChartTime('2026-08-06')).toBe('2026-08-06');
  });

  it('shifts epoch zero rather than treating it as absent', () => {
    expect(toChartTime(0)).toBe(DISPLAY_TZ_OFFSET_S);
  });
});

describe('fromChartTime', () => {
  it('shifts a numeric epoch back by the display offset', () => {
    expect(fromChartTime(EPOCH)).toBe(EPOCH - DISPLAY_TZ_OFFSET_S);
  });

  it('leaves a date string untouched', () => {
    expect(fromChartTime('2026-08-06')).toBe('2026-08-06');
  });
});

describe('drawingEpoch', () => {
  /**
   * The conversion trendlines were missing. `fromChartTime` passes a date string
   * through untouched — right for a bar, wrong for a drawing, whose `t1`/`t2`
   * are an integer column the backend does arithmetic on. Posting the string
   * answered **422 `int_parsing`** and `.catch(() => {})` swallowed it, so
   * trendlines silently could not be saved on any daily-or-coarser range.
   */
  it('takes the display offset back off an intraday timestamp', () => {
    expect(drawingEpoch(EPOCH + DISPLAY_TZ_OFFSET_S)).toBe(EPOCH);
  });

  it('converts a date string, which is what a daily chart returns', () => {
    expect(drawingEpoch('2026-08-06')).toBe(Date.UTC(2026, 7, 6) / 1000);
  });

  it('converts a business day, which coordinateToTime can also return', () => {
    expect(drawingEpoch({ year: 2026, month: 8, day: 6 })).toBe(Date.UTC(2026, 7, 6) / 1000);
  });

  it('returns null rather than something unparseable', () => {
    // the caller refuses to POST on null, because the API's own answer is a 422
    // nobody sees
    expect(drawingEpoch('not-a-date')).toBeNull();
    expect(drawingEpoch(null)).toBeNull();
    expect(drawingEpoch(undefined)).toBeNull();
    expect(drawingEpoch({})).toBeNull();
  });

  it('always yields an integer, because the column is one', () => {
    for (const t of [EPOCH + DISPLAY_TZ_OFFSET_S, '2026-08-06', { year: 2026, month: 8, day: 6 }]) {
      expect(Number.isInteger(drawingEpoch(t))).toBe(true);
    }
  });
});

describe('drawingChartTime', () => {
  it('shifts into the display zone for an intraday series', () => {
    expect(drawingChartTime(EPOCH, true)).toBe(EPOCH + DISPLAY_TZ_OFFSET_S);
  });

  it('renders a date string for a daily series, which addresses its axis that way', () => {
    expect(drawingChartTime(Date.UTC(2026, 7, 6) / 1000, false)).toBe('2026-08-06');
  });

  it('round-trips through drawingEpoch in both representations', () => {
    // What makes a drawing survive a change of period: one stored number
    // becomes whichever shape the new series speaks.
    const epoch = Date.UTC(2026, 7, 6) / 1000;
    expect(drawingEpoch(drawingChartTime(epoch, false))).toBe(epoch);
    expect(drawingEpoch(drawingChartTime(epoch, true))).toBe(epoch);
  });

  it('passes a null through rather than inventing 1970', () => {
    expect(drawingChartTime(null, false)).toBeNull();
    expect(drawingChartTime(undefined, true)).toBeNull();
  });
});

describe('the round trip', () => {
  it('returns a numeric epoch exactly, so a stored drawing cannot drift', () => {
    for (const t of [0, 1, EPOCH, -EPOCH, 2 ** 31]) {
      expect(fromChartTime(toChartTime(t))).toBe(t);
      expect(toChartTime(fromChartTime(t))).toBe(t);
    }
  });

  it('returns a date string exactly', () => {
    expect(fromChartTime(toChartTime('2026-08-06'))).toBe('2026-08-06');
  });
});
