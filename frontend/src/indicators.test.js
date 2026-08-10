/**
 * Indicator math.
 *
 * These functions had no tests, which made them the largest piece of unaudited
 * numerical code in the frontend. An off-by-one in an EMA seed or a Wilder
 * smoothing step does not look wrong on a chart — the line still curves, still
 * crosses, still sits between 0 and 100. It just answers a different question
 * than the one the label claims, which is the same failure mode the event-marker
 * timezone bug had.
 *
 * Expected values are established two ways, deliberately not from the
 * implementation under test: small cases whose arithmetic is written out in the
 * comment, and Wilder's own worked dataset computed independently from the
 * formula in "New Concepts in Technical Trading Systems".
 */
import { describe, it, expect } from 'vitest';
import { barsForDays, macdSeries, rsiSeries, smaSeries } from './indicators';

const bars = (closes) => closes.map((close, i) => ({ time: i, close }));
const values = (series) => series.map((p) => p.value);

describe('barsForDays', () => {
  it('scales a day window by the measured bars per day', () => {
    expect(barsForDays(50, 7)).toBe(350);
  });

  it('treats a missing bars-per-day as one bar per day', () => {
    expect(barsForDays(50, 0)).toBe(50);
    expect(barsForDays(50, undefined)).toBe(50);
  });

  it('never returns a window too short to be a window', () => {
    // 1 day of daily bars would otherwise be a 1-bar "average"
    expect(barsForDays(1, 1)).toBe(2);
  });
});

describe('smaSeries', () => {
  it('averages the trailing window', () => {
    // [1,2,3,4,5] period 3 -> (1+2+3)/3, (2+3+4)/3, (3+4+5)/3
    expect(values(smaSeries(bars([1, 2, 3, 4, 5]), 3))).toEqual([2, 3, 4]);
  });

  it('emits nothing until a full window exists', () => {
    expect(smaSeries(bars([1, 2]), 3)).toEqual([]);
  });

  it('anchors each point at the newest bar in its window, not the oldest', () => {
    // the running sum drops bars[i-period]; getting that index wrong shifts the
    // whole line sideways, which is invisible on a chart
    expect(smaSeries(bars([1, 2, 3, 4, 5]), 3)[0].time).toBe(2);
  });

  it('does not drift on a long series', () => {
    const flat = smaSeries(bars(Array(500).fill(7)), 50);
    expect(flat.every((p) => Math.abs(p.value - 7) < 1e-9)).toBe(true);
  });
});

describe('rsiSeries — Wilder smoothing', () => {
  it('matches an arithmetic worked by hand', () => {
    // closes 10, 11, 10, 12, 13 with period 3.
    //   deltas         +1, -1, +2, +1
    //   seed (3 deltas) avgGain (1+0+2)/3 = 1      avgLoss (0+1+0)/3 = 1/3
    //   RSI            100 - 100/(1 + 1/(1/3))     = 100 - 25       = 75
    //   next delta +1   avgGain (1*2 + 1)/3   = 1
    //                   avgLoss ((1/3)*2 + 0)/3 = 2/9
    //   RSI            100 - 100/(1 + 1/(2/9))     = 100 - 100/5.5  = 81.818…
    //
    // Period 3, not 2, on purpose: at period 2 the Wilder recurrence
    // (avg*(n-1) + x)/n collapses to a plain (avg + x)/2, so a two-period case
    // cannot tell Wilder smoothing from a simple mean. Verified by mutation —
    // at period 2 the swap survives, at period 3 it fails here.
    const out = rsiSeries(bars([10, 11, 10, 12, 13]), 3);
    expect(values(out)[0]).toBeCloseTo(75, 10);
    expect(values(out)[1]).toBeCloseTo(100 - 100 / 5.5, 10);
  });

  it('reproduces Wilder\'s worked dataset', () => {
    // Computed from Wilder's formula independently of this module. Agrees with
    // the published table to ~0.07, which is transcription rounding in the
    // printed closes rather than a difference in method.
    const closes = [
      44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.1, 45.42, 45.84, 46.08,
      45.89, 46.03, 45.61, 46.28, 46.28, 46.0, 46.03, 46.41, 46.22, 45.64,
      46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22, 44.57,
      43.42, 42.66, 43.13,
    ];
    const expected = [
      70.46, 66.25, 66.48, 69.35, 66.29, 57.92, 62.88, 63.21, 56.01, 62.34,
      54.67, 50.39, 40.02, 41.49, 41.9, 45.5, 37.32, 33.09, 37.79,
    ];
    const out = values(rsiSeries(bars(closes), 14));

    expect(out).toHaveLength(expected.length);
    out.forEach((v, i) => expect(v).toBeCloseTo(expected[i], 1));
  });

  it('starts at the bar the first average covers', () => {
    // period+1 closes give exactly one reading, at bars[period]
    const out = rsiSeries(bars([1, 2, 3, 4, 5]), 4);
    expect(out).toHaveLength(1);
    expect(out[0].time).toBe(4);
  });

  it('emits nothing when there are not enough bars to seed', () => {
    expect(rsiSeries(bars([1, 2, 3, 4]), 4)).toEqual([]);
  });

  it('pins 100 for an unbroken advance and 0 for an unbroken decline', () => {
    expect(values(rsiSeries(bars([1, 2, 3, 4, 5, 6]), 3)).every((v) => v === 100)).toBe(true);
    expect(values(rsiSeries(bars([6, 5, 4, 3, 2, 1]), 3)).every((v) => v === 0)).toBe(true);
  });

  it('stays inside 0-100 on a noisy series', () => {
    const closes = Array.from({ length: 300 }, (_, i) => 100 + Math.sin(i / 3) * 20 + (i % 7));
    expect(values(rsiSeries(bars(closes), 14)).every((v) => v >= 0 && v <= 100)).toBe(true);
  });
});

describe('macdSeries — EMA construction and alignment', () => {
  const ramp = (n) => bars(Array.from({ length: n }, (_, i) => 100 + i));

  it('is flat at zero on a constant series', () => {
    // every EMA of a constant equals that constant, so the difference is zero —
    // the cheapest check that the seeds are not off
    const { macd, signal, hist } = macdSeries(bars(Array(60).fill(50)));
    expect(values(macd).every((v) => Math.abs(v) < 1e-9)).toBe(true);
    expect(values(signal).every((v) => Math.abs(v) < 1e-9)).toBe(true);
    expect(values(hist).every((v) => Math.abs(v) < 1e-9)).toBe(true);
  });

  it('starts the MACD line where the slow EMA first exists', () => {
    // slow = 26, seeded with an SMA of the first 26 closes, so index 25
    const { macd } = macdSeries(ramp(60));
    expect(macd).toHaveLength(60 - 25);
    expect(macd[0].time).toBe(25);
  });

  it('starts the signal line nine MACD values later', () => {
    // signal is an EMA(9) of the MACD line, itself SMA-seeded: index 25 + 8
    const { signal } = macdSeries(ramp(60));
    expect(signal).toHaveLength(60 - 33);
    expect(signal[0].time).toBe(33);
  });

  it('emits nothing when the series is shorter than the slow window', () => {
    expect(macdSeries(ramp(20))).toEqual({ macd: [], signal: [], hist: [] });
  });

  it('is positive on a rising series, because the fast EMA lags less', () => {
    const { macd } = macdSeries(ramp(120));
    expect(macd[macd.length - 1].value).toBeGreaterThan(0);
  });

  it('seeds each EMA with an SMA of its first window', () => {
    // On a slope-1 ramp an EMA in steady state lags the current value by
    // exactly (period-1)/2, and the SMA of a linear window equals the value at
    // that window's midpoint — so an SMA-seeded EMA is *already* at its steady
    // state on its first bar. MACD's first point is therefore exactly
    //   12.5 - 5.5 = 7
    // and stays there. Seeding with the raw close instead gives -4.9695 here.
    //
    // This is the only assertion that pins the seed: on a constant series both
    // conventions agree, and on a ramp both converge to 7 within ~2e-5 by bar
    // 200. Verified by mutation — seeding with values[period-1] survives every
    // other test in this file.
    const { macd } = macdSeries(ramp(200));
    expect(macd[0].value).toBeCloseTo(7, 9);
    expect(macd[macd.length - 1].value).toBeCloseTo(7, 9);
  });

  it('reports the histogram as MACD minus signal, on shared timestamps', () => {
    const { macd, signal, hist } = macdSeries(ramp(60));
    const macdAt = new Map(macd.map((p) => [p.time, p.value]));
    expect(hist).toHaveLength(signal.length);
    hist.forEach((h, i) => {
      expect(h.time).toBe(signal[i].time);
      expect(h.value).toBeCloseTo(macdAt.get(h.time) - signal[i].value, 10);
    });
  });

  it('colours the histogram by its own sign', () => {
    const { hist } = macdSeries(bars(
      Array.from({ length: 120 }, (_, i) => 100 + Math.sin(i / 8) * 15),
    ));
    expect(hist.some((h) => h.value > 0)).toBe(true);
    expect(hist.some((h) => h.value < 0)).toBe(true);
    expect(hist.every((h) => (h.value >= 0) === h.color.includes('46, 189, 133'))).toBe(true);
  });

  it('honours non-default periods', () => {
    const { macd, signal } = macdSeries(ramp(40), 3, 6, 4);
    expect(macd[0].time).toBe(5);        // slow - 1
    expect(signal[0].time).toBe(5 + 3);  // + (signalPeriod - 1)
  });
});
