// Trendline and horizontal-level rendering for lightweight-charts.
//
// lightweight-charts@5 ships no drawing tools — only the primitive API
// (attachPrimitive / ISeriesPrimitive) — so the line, its handles and its hit
// testing are all drawn and computed here.
//
// Times handled here are CHART-SPACE (GMT+8 shifted, see charttime.js).
// Conversion back to true epochs happens at the persistence boundary in
// PriceChart, so nothing in this file needs to know the display timezone.

const HIT_TOLERANCE_PX = 6;
const HANDLE_RADIUS_PX = 5;

// Readability over candles, which is the background these lines actually sit
// on. Two changes carry it: a wider stroke, and a dark halo drawn underneath at
// stroke+3 so the line separates from a green or red body instead of merging
// into it. The halo is why the colours themselves did not have to get louder —
// contrast comes from the outline, not from saturation.
const LINE_WIDTH_PX = 2;
const LINE_WIDTH_SELECTED_PX = 3;
const HALO_COLOR = 'rgba(11, 15, 20, 0.75)';
const COLORS = { hline: '#fbbf24', trendline: '#60a5fa' };
// The line being placed, before its second click exists. Dashed and dimmed so
// it reads as "not yet a drawing" rather than as one that failed to save.
const PREVIEW_COLOR = 'rgba(96, 165, 250, 0.8)';
const PREVIEW_DASH = [5, 4];
// The crosshair's own price line, standing in for the chart's — see
// `crosshairShape`. Deliberately neutral and thin: it marks where the pointer
// is, not a level anyone drew, so it must not compete with an `hline` the
// reader placed on purpose. Dashed on the same rhythm as the preview, which is
// the vocabulary this chart already uses for "transient".
const CROSSHAIR_COLOR = 'rgba(190, 205, 220, 0.9)';
const CROSSHAIR_DASH = [4, 3];
const CROSSHAIR_WIDTH_PX = 1;
// The axis pill for that line. Opaque rather than the line's own translucent
// grey: it sits on the axis gutter over tick labels, and the price has to be
// readable through nothing.
const CROSSHAIR_LABEL_BACK = '#4b5563';
const CROSSHAIR_LABEL_TEXT = '#f3f4f6';
// Returned whenever there is no crosshair, as a module constant rather than a
// fresh `[]`. `priceAxisViews` is called on essentially every repaint and the
// library caches on reference identity, so a new empty array each time would
// rebuild its wrappers on every pointer move for no change at all.
const NO_AXIS_VIEWS = [];

/**
 * A chart time as a number that can be compared, whatever shape it arrived in.
 *
 * lightweight-charts carries three: a UNIX timestamp for intraday bars, an ISO
 * date string for daily and coarser ones (see charttime.js — only intraday is
 * shifted), and a `{year, month, day}` business day, which `coordinateToTime`
 * can return even when the series was given strings. Snapping has to work on
 * the daily chart, which is the string case, so subtracting the raw values
 * would have produced `NaN` on the most common range in the app.
 */
function timeValue(t) {
  if (typeof t === 'number') return t;
  if (typeof t === 'string') return Date.parse(t);
  if (t && typeof t === 'object' && t.year != null) {
    return Date.UTC(t.year, (t.month ?? 1) - 1, t.day ?? 1);
  }
  return NaN;
}

/**
 * Pull a placed point onto the nearest real value on the nearest bar.
 *
 * A click lands on a pixel, and a pixel is not a number anybody reported. At a
 * typical price scale one pixel is worth a few cents, so a trendline drawn
 * "along the highs" by eye actually connects two arbitrary values near them and
 * the level it projects is off by however far the hand was. Snapping puts both
 * ends on figures that exist in the data.
 *
 * The bar is chosen by time and then the price by absolute distance across all
 * four of open/high/low/close, so anchoring to a wick works as well as to a
 * body — dragging near a spike high gives the high, not the close.
 *
 * `bars` is the chart-space series, ascending by time. Returns the input
 * unchanged when there is nothing to snap to, which keeps the caller free of
 * the empty and out-of-range cases.
 */
export function snapToBar(bars, time, price) {
  if (!bars?.length || time == null || price == null) return { time, price };
  const target = timeValue(time);
  if (!Number.isFinite(target)) return { time, price };
  let best = null;
  let bestGap = Infinity;
  for (const bar of bars) {
    const value = timeValue(bar.time);
    if (!Number.isFinite(value)) continue;
    const gap = Math.abs(value - target);
    // ascending, so once the gap starts growing the nearest bar is behind us
    if (gap > bestGap) break;
    bestGap = gap;
    best = bar;
  }
  if (!best) return { time, price };
  const candidates = [best.open, best.high, best.low, best.close]
    .filter((v) => typeof v === 'number' && Number.isFinite(v));
  if (!candidates.length) return { time: best.time, price };
  const snapped = candidates.reduce(
    (a, b) => (Math.abs(b - price) < Math.abs(a - price) ? b : a));
  return { time: best.time, price: snapped };
}

/** Where a line sits, in price, at a given chart time. Extends beyond its ends. */
export function linePriceAt(drawing, time) {
  if (drawing.kind === 'hline') return drawing.p1;
  const { t1, t2, p1, p2 } = drawing;
  if (t1 == null || t2 == null || p1 == null || p2 == null || t2 === t1) return null;
  return p1 + ((p2 - p1) * (time - t1)) / (t2 - t1);
}

/**
 * Distance from a point to the **segment**, in pixels.
 *
 * This measured the distance to the segment's *infinite* line until 2026-08-20,
 * justified by a comment claiming "the rendered line is also extended past its
 * endpoints". It is not — `DrawingsRenderer` draws `moveTo(x1,y1)` then
 * `lineTo(x2,y2)`, a plain segment. So every trendline carried an invisible
 * selection corridor running the full width and height of the chart along its
 * own extension: clicking empty space that happened to line up with an old
 * trendline selected it, and on a steep line that corridor swept most of the
 * pane.
 *
 * The projection is clamped to [0, 1], which is the only difference — beyond an
 * endpoint the distance becomes the distance to that endpoint. Horizontal lines
 * are unaffected either way: their shape already spans the full width, so no
 * point on screen is ever past an end.
 */
function distanceToSegment(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return Math.hypot(px - x1, py - y1);
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lengthSquared));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

class DrawingsRenderer {
  constructor(source) {
    this._source = source;
  }

  draw(target) {
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const ratio = scope.horizontalPixelRatio;
      const vRatio = scope.verticalPixelRatio;

      const stroke = (x1, y1, x2, y2, width, color, dash) => {
        ctx.beginPath();
        ctx.moveTo(x1 * ratio, y1 * vRatio);
        ctx.lineTo(x2 * ratio, y2 * vRatio);
        // The halo goes down first and slightly wider, so the coloured stroke
        // sits inside it. Dashed lines skip it — a halo through the gaps would
        // read as a solid line with a coloured pattern on top.
        if (!dash) {
          ctx.setLineDash([]);
          ctx.lineWidth = (width + 3) * vRatio;
          ctx.strokeStyle = HALO_COLOR;
          ctx.stroke();
        }
        ctx.setLineDash(dash ? dash.map((n) => n * ratio) : []);
        ctx.lineWidth = width * vRatio;
        ctx.strokeStyle = color;
        ctx.stroke();
        ctx.setLineDash([]);
      };

      for (const shape of this._source.screenShapes()) {
        const selected = shape.id === this._source.selectedId();
        const color = COLORS[shape.kind] ?? COLORS.trendline;
        ctx.save();
        stroke(shape.x1, shape.y1, shape.x2, shape.y2,
               selected ? LINE_WIDTH_SELECTED_PX : LINE_WIDTH_PX, color);

        // handles only on the selected shape, so an unselected chart stays clean
        if (selected) {
          for (const [hx, hy] of shape.handles) {
            ctx.beginPath();
            ctx.arc(hx * ratio, hy * vRatio, HANDLE_RADIUS_PX * ratio, 0, Math.PI * 2);
            ctx.fillStyle = '#fff';
            ctx.fill();
            // dark rim rather than the line's own colour: a white dot on a pale
            // candle was invisible, and the rim is what gives it an edge
            ctx.lineWidth = 2 * vRatio;
            ctx.strokeStyle = HALO_COLOR;
            ctx.stroke();
          }
        }

        if (shape.label) {
          ctx.font = `${11 * vRatio}px system-ui, sans-serif`;
          ctx.lineWidth = 3 * vRatio;
          ctx.strokeStyle = HALO_COLOR;
          ctx.strokeText(shape.label, (shape.x2 + 6) * ratio, (shape.y2 - 4) * vRatio);
          ctx.fillStyle = color;
          ctx.fillText(shape.label, (shape.x2 + 6) * ratio, (shape.y2 - 4) * vRatio);
        }
        ctx.restore();
      }

      // The trendline being placed. Drawn after the saved ones so it is never
      // hidden behind them, and it is deliberately not in `screenShapes` — it
      // has no id, cannot be selected, and must not be hit-testable.
      const preview = this._source.previewShape();
      if (preview) {
        ctx.save();
        stroke(preview.x1, preview.y1, preview.x2, preview.y2,
               LINE_WIDTH_PX, PREVIEW_COLOR, PREVIEW_DASH);
        ctx.restore();
      }

      // The crosshair's price line, last so it is never hidden behind a
      // drawing — it tracks the pointer, and a pointer indicator that
      // disappears under the thing being pointed at is the one case it must
      // not fail. Not hit-testable, for the same reason the preview is not.
      const crosshair = this._source.crosshairShape();
      if (crosshair) {
        ctx.save();
        stroke(crosshair.x1, crosshair.y1, crosshair.x2, crosshair.y2,
               CROSSHAIR_WIDTH_PX, CROSSHAIR_COLOR, CROSSHAIR_DASH);
        ctx.restore();
      }
    });
  }
}

/**
 * The price label for the crosshair line, on the series' own price axis.
 *
 * `fixedCoordinate` is deliberately not implemented. It is optional, and a view
 * that pins its coordinate is excluded from the pass that pushes overlapping
 * axis labels apart — which is exactly what stops this label sitting on top of
 * the series' own last-value label. Leaving it off is what buys that for free.
 */
class CrosshairAxisView {
  constructor(source) {
    this._source = source;
  }

  coordinate() {
    // Only read while `visible()` is true, but the library asks for it either
    // way on some paths, and a `null` here would be drawn at the top of the
    // axis rather than nowhere.
    return this._source.crosshairShape()?.y1 ?? 0;
  }

  text() {
    const price = this._source.crosshairPrice();
    return price == null ? '' : price.toFixed(2);
  }

  textColor() {
    return CROSSHAIR_LABEL_TEXT;
  }

  backColor() {
    return CROSSHAIR_LABEL_BACK;
  }

  visible() {
    return this._source.crosshairShape() !== null;
  }
}

/**
 * Series primitive holding every drawing for the current ticker.
 *
 * It reads its data through callbacks rather than owning it, so React stays the
 * single source of truth and a re-render does not have to rebuild the chart.
 */
export class DrawingsPrimitive {
  constructor({ getDrawings, getSelectedId, getPreview, getCrosshair }) {
    this._getDrawings = getDrawings;
    this._getSelectedId = getSelectedId;
    // `{t1, p1, t2, p2}` while a trendline is half-placed, else null. A callback
    // like the other two so the chart never has to be rebuilt to show it.
    this._getPreview = getPreview ?? (() => null);
    // `{price}` while the pointer is over the chart with the magnet on, else
    // null. Optional for the same reason as the preview: a caller that does not
    // want a crosshair should not have to pass one.
    this._getCrosshair = getCrosshair ?? (() => null);
    this._series = null;
    this._chart = null;
    this._renderer = new DrawingsRenderer(this);
    this._requestUpdate = null;
    // Built once and handed back by reference; see `NO_AXIS_VIEWS`.
    this._axisViews = [new CrosshairAxisView(this)];
  }

  attached({ chart, series, requestUpdate }) {
    this._chart = chart;
    this._series = series;
    this._requestUpdate = requestUpdate;
  }

  detached() {
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
  }

  /** Ask lightweight-charts to repaint — call after any drawing state change. */
  update() {
    this._requestUpdate?.();
  }

  selectedId() {
    return this._getSelectedId();
  }

  paneViews() {
    return [{ renderer: () => this._renderer, zOrder: () => 'top' }];
  }

  /** The price the crosshair line is drawn at, or null. */
  crosshairPrice() {
    return this._getCrosshair()?.price ?? null;
  }

  /** The axis label for that line — one view, or none. */
  priceAxisViews() {
    return this.crosshairShape() ? this._axisViews : NO_AXIS_VIEWS;
  }

  /** Pixel geometry for the trendline being placed, or null. */
  previewShape() {
    if (!this._series || !this._chart) return null;
    const p = this._getPreview();
    if (!p || p.t1 == null || p.t2 == null || p.p1 == null || p.p2 == null) return null;
    const timeScale = this._chart.timeScale();
    const x1 = timeScale.timeToCoordinate(p.t1);
    const x2 = timeScale.timeToCoordinate(p.t2);
    const y1 = this._series.priceToCoordinate(p.p1);
    const y2 = this._series.priceToCoordinate(p.p2);
    if (x1 == null || x2 == null || y1 == null || y2 == null) return null;
    return { x1, y1, x2, y2 };
  }

  /**
   * Pixel geometry for the crosshair's own price line, or null.
   *
   * The chart's crosshair cannot do this. Neither magnet mode can be told which
   * series to snap to — both are documented as snapping to "the price value of
   * a single-value series", and a moving average overlay is one — so with MAs
   * drawn the library's line settles on whichever series is nearest the pointer
   * while the readout beside it reports the bar. The caller passes a price
   * already snapped by `snapToBar`, and this places it.
   *
   * Full width, like an `hline`, and returned in the same `{x1,y1,x2,y2}` shape
   * so the renderer strokes it with the code that already exists.
   */
  crosshairShape() {
    if (!this._series || !this._chart) return null;
    const c = this._getCrosshair();
    if (!c || c.price == null) return null;
    const y = this._series.priceToCoordinate(c.price);
    // null outside the plotted range. Drawing at `null` would put the line at
    // the top of the pane rather than nowhere, which is the one wrong answer.
    if (y == null) return null;
    return { x1: 0, y1: y, x2: this._chart.timeScale().width(), y2: y };
  }

  /** Pixel geometry for every drawing, given the current pan/zoom. */
  screenShapes() {
    if (!this._series || !this._chart) return [];
    const timeScale = this._chart.timeScale();
    const width = timeScale.width();
    const shapes = [];

    for (const d of this._getDrawings()) {
      if (d.kind === 'hline') {
        const y = this._series.priceToCoordinate(d.p1);
        if (y == null) continue;
        shapes.push({
          id: d.id, kind: d.kind, x1: 0, y1: y, x2: width, y2: y,
          handles: [[width / 2, y]],
          label: d.label || d.p1.toFixed(2),
        });
      } else {
        const y1 = this._series.priceToCoordinate(d.p1);
        const y2 = this._series.priceToCoordinate(d.p2);
        const x1 = timeScale.timeToCoordinate(d.t1);
        const x2 = timeScale.timeToCoordinate(d.t2);
        if (y1 == null || y2 == null || x1 == null || x2 == null) continue;
        shapes.push({
          id: d.id, kind: d.kind, x1, y1, x2, y2,
          handles: [[x1, y1], [x2, y2]],
          label: d.label || '',
        });
      }
    }
    return shapes;
  }

  /** The drawing under a click, plus which handle if any. Null when nothing is. */
  hitTest(x, y) {
    for (const shape of [...this.screenShapes()].reverse()) {
      for (let i = 0; i < shape.handles.length; i++) {
        const [hx, hy] = shape.handles[i];
        if (Math.hypot(x - hx, y - hy) <= HANDLE_RADIUS_PX + HIT_TOLERANCE_PX) {
          return { id: shape.id, handle: i };
        }
      }
      if (distanceToSegment(x, y, shape.x1, shape.y1, shape.x2, shape.y2) <= HIT_TOLERANCE_PX) {
        return { id: shape.id, handle: null };
      }
    }
    return null;
  }

  /** Pixel -> (chart time, price). Returns nulls outside the plotted area. */
  toDataPoint(x, y) {
    if (!this._series || !this._chart) return { time: null, price: null };
    return {
      time: this._chart.timeScale().coordinateToTime(x),
      price: this._series.coordinateToPrice(y),
    };
  }
}
