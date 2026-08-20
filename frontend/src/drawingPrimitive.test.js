/**
 * The geometry behind the drawing tools.
 *
 * Everything here is pure or driven through fake chart/series objects, so it
 * runs without a canvas — which is why these are the assertions that can exist
 * at all. `PriceChart.test.jsx` explains why the chart itself is mocked rather
 * than rendered.
 */
import { describe, it, expect } from 'vitest';
import { DrawingsPrimitive, snapToBar } from './drawingPrimitive';

/**
 * A primitive whose pixel space is the identity, so a drawing's coordinates and
 * the pixels asserted against are the same numbers.
 */
function primitiveWith(drawings, { width = 800 } = {}) {
  const p = new DrawingsPrimitive({
    getDrawings: () => drawings,
    getSelectedId: () => null,
  });
  p.attached({
    chart: { timeScale: () => ({ width: () => width, timeToCoordinate: (t) => t }) },
    series: { priceToCoordinate: (v) => v },
    requestUpdate: () => {},
  });
  return p;
}

// runs (100,100) -> (200,200): slope 1, so its infinite extension sweeps the
// whole diagonal of any chart it is drawn on
const DIAGONAL = [{ id: 1, kind: 'trendline', t1: 100, p1: 100, t2: 200, p2: 200 }];

describe('hit testing a trendline', () => {
  it('selects a click on the segment', () => {
    expect(primitiveWith(DIAGONAL).hitTest(150, 150)).toEqual({ id: 1, handle: null });
  });

  it('ignores a click past the end, on the line the segment does not draw', () => {
    /**
     * The defect this fixes. The distance was measured to the segment's
     * *infinite* line, justified by a comment claiming the renderer extends past
     * the endpoints — it does not, it draws `moveTo(x1,y1)` then `lineTo(x2,y2)`.
     * So every trendline carried an invisible selection corridor running the
     * full diagonal of the chart, and clicking empty space that happened to line
     * up with an old line selected it.
     *
     * (600, 600) is exactly on the extension and 400px past the end. Under the
     * old form its distance was 0 and it selected; it must now miss.
     */
    expect(primitiveWith(DIAGONAL).hitTest(600, 600)).toBeNull();
    expect(primitiveWith(DIAGONAL).hitTest(20, 20)).toBeNull(); // past the start
  });

  it('still measures perpendicular distance within the segment', () => {
    // ~3.5px off the line, inside the 6px tolerance
    expect(primitiveWith(DIAGONAL).hitTest(150, 155)).toEqual({ id: 1, handle: null });
    // ~14px off, outside it
    expect(primitiveWith(DIAGONAL).hitTest(150, 170)).toBeNull();
  });

  it('reports the handle when the click is on an endpoint', () => {
    expect(primitiveWith(DIAGONAL).hitTest(100, 100)).toEqual({ id: 1, handle: 0 });
    expect(primitiveWith(DIAGONAL).hitTest(200, 200)).toEqual({ id: 1, handle: 1 });
  });
});

describe('hit testing a horizontal line', () => {
  const HLINE = [{ id: 2, kind: 'hline', p1: 300 }];

  it('selects anywhere along the width it is actually drawn across', () => {
    const p = primitiveWith(HLINE, { width: 800 });
    expect(p.hitTest(0, 300)).toEqual({ id: 2, handle: null });
    expect(p.hitTest(799, 300)).toEqual({ id: 2, handle: null });
  });

  it('is unaffected by the segment change, because it spans the whole pane', () => {
    // No point on screen is past its ends, so clamping the projection cannot
    // change any answer for this kind — asserted so the fix is known to be
    // confined to trendlines.
    const p = primitiveWith(HLINE, { width: 800 });
    expect(p.hitTest(400, 320)).toBeNull(); // 20px away, still a miss
  });
});

describe('the preview line', () => {
  it('is not hit-testable, because it is not a drawing yet', () => {
    const p = new DrawingsPrimitive({
      getDrawings: () => [],
      getSelectedId: () => null,
      getPreview: () => ({ t1: 100, p1: 100, t2: 200, p2: 200 }),
    });
    p.attached({
      chart: { timeScale: () => ({ width: () => 800, timeToCoordinate: (t) => t }) },
      series: { priceToCoordinate: (v) => v },
      requestUpdate: () => {},
    });
    expect(p.previewShape()).toEqual({ x1: 100, y1: 100, x2: 200, y2: 200 });
    expect(p.hitTest(150, 150)).toBeNull();
  });

  it('is absent when no line is being placed', () => {
    expect(primitiveWith([]).previewShape()).toBeNull();
  });
});

describe('snapToBar', () => {
  const DAILY = [
    { time: '2026-01-05', open: 100, high: 110, low: 95, close: 104 },
    { time: '2026-01-06', open: 104, high: 112, low: 103, close: 108 },
    { time: '2026-01-07', open: 108, high: 115, low: 106, close: 111 },
  ];

  it('pulls the price onto the nearest of open/high/low/close', () => {
    expect(snapToBar(DAILY, '2026-01-06', 111.4)).toEqual({ time: '2026-01-06', price: 112 });
  });

  it('can anchor to a wick, not just a body', () => {
    // 106.4 is nearer the low (106) than the close (111) — dragging at a spike
    // has to give the spike, which is the whole reason all four are candidates
    expect(snapToBar(DAILY, '2026-01-07', 106.4)).toEqual({ time: '2026-01-07', price: 106 });
  });

  it('works on date strings, which is what a daily chart carries', () => {
    /**
     * charttime.js shifts only intraday bars, so daily and coarser ones stay
     * ISO strings — and `6mo`, `1y`, `2y` are all daily. Subtracting the raw
     * values would be `NaN` on the most-used ranges in the app, so the
     * comparison converts first.
     */
    expect(snapToBar(DAILY, '2026-01-05', 96).time).toBe('2026-01-05');
  });

  it('works on a business-day object, which coordinateToTime can return', () => {
    expect(snapToBar(DAILY, { year: 2026, month: 1, day: 5 }, 96))
      .toEqual({ time: '2026-01-05', price: 95 });
  });

  it('works on numeric intraday times', () => {
    const intraday = [
      { time: 1000, open: 10, high: 12, low: 9, close: 11 },
      { time: 2000, open: 11, high: 14, low: 10, close: 13 },
    ];
    expect(snapToBar(intraday, 1900, 13.6)).toEqual({ time: 2000, price: 14 });
  });

  it('returns the point untouched when there is nothing to snap to', () => {
    // the caller passes straight through rather than special-casing these
    expect(snapToBar([], '2026-01-06', 111.4)).toEqual({ time: '2026-01-06', price: 111.4 });
    expect(snapToBar(DAILY, '2026-01-06', null)).toEqual({ time: '2026-01-06', price: null });
    expect(snapToBar(DAILY, 'not-a-date', 100)).toEqual({ time: 'not-a-date', price: 100 });
    expect(snapToBar(null, 1, 2)).toEqual({ time: 1, price: 2 });
  });
});
