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
const HANDLE_RADIUS_PX = 4;

/** Where a line sits, in price, at a given chart time. Extends beyond its ends. */
export function linePriceAt(drawing, time) {
  if (drawing.kind === 'hline') return drawing.p1;
  const { t1, t2, p1, p2 } = drawing;
  if (t1 == null || t2 == null || p1 == null || p2 == null || t2 === t1) return null;
  return p1 + ((p2 - p1) * (time - t1)) / (t2 - t1);
}

/**
 * Perpendicular distance from a point to the segment's infinite line, in pixels.
 * Used for click selection; the infinite form is right because the rendered line
 * is also extended past its endpoints.
 */
function distanceToLine(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  if (dx === 0 && dy === 0) return Math.hypot(px - x1, py - y1);
  return Math.abs(dy * px - dx * py + x2 * y1 - y2 * x1) / Math.hypot(dx, dy);
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
      for (const shape of this._source.screenShapes()) {
        const selected = shape.id === this._source.selectedId();
        ctx.save();
        ctx.lineWidth = (selected ? 2 : 1.5) * vRatio;
        ctx.strokeStyle = shape.kind === 'hline' ? '#f0b90b' : '#3b82f6';
        if (selected) ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(shape.x1 * ratio, shape.y1 * vRatio);
        ctx.lineTo(shape.x2 * ratio, shape.y2 * vRatio);
        ctx.stroke();

        // handles only on the selected shape, so an unselected chart stays clean
        if (selected) {
          ctx.fillStyle = '#fff';
          for (const [hx, hy] of shape.handles) {
            ctx.beginPath();
            ctx.arc(hx * ratio, hy * vRatio, HANDLE_RADIUS_PX * ratio, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
          }
        }

        if (shape.label) {
          ctx.fillStyle = shape.kind === 'hline' ? '#f0b90b' : '#3b82f6';
          ctx.font = `${11 * vRatio}px system-ui, sans-serif`;
          ctx.fillText(shape.label, (shape.x2 + 6) * ratio, (shape.y2 - 4) * vRatio);
        }
        ctx.restore();
      }
    });
  }
}

/**
 * Series primitive holding every drawing for the current ticker.
 *
 * It reads its data through callbacks rather than owning it, so React stays the
 * single source of truth and a re-render does not have to rebuild the chart.
 */
export class DrawingsPrimitive {
  constructor({ getDrawings, getSelectedId }) {
    this._getDrawings = getDrawings;
    this._getSelectedId = getSelectedId;
    this._series = null;
    this._chart = null;
    this._renderer = new DrawingsRenderer(this);
    this._requestUpdate = null;
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
      if (distanceToLine(x, y, shape.x1, shape.y1, shape.x2, shape.y2) <= HIT_TOLERANCE_PX) {
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
