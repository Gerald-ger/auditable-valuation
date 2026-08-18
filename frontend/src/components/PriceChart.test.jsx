/**
 * @vitest-environment jsdom
 *
 * The chart/drawings boundary, which is the part of this component that has no
 * other guard.
 *
 * `lightweight-charts` is mocked wholesale rather than driven for real. That is
 * not a shortcut: measured 2026-08-18, rendering it under jsdom fails with eight
 * errors — it needs `ResizeObserver`, a canvas 2D context and a
 * `devicePixelRatio` observable, and ends in `Error: Value is null` inside
 * `PriceAxisWidget._internal_optimalWidth`. Making that work needs the native
 * `canvas` package. Nothing here tries to assert what the chart *draws*.
 *
 * What the mock does buy is the seam this component is actually built on. The
 * chart effect constructs `DrawingsPrimitive` and hands it two callbacks that
 * read the drawing state; the drawing effect reaches back and switches the
 * chart's pan/zoom off while a tool is active. Those two edges are the whole
 * contract between the two halves of this file, they are invisible in a diff,
 * and the project's linter does not run `exhaustive-deps`, so nothing else would
 * catch them changing.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import PriceChart from './PriceChart';
import { render, click, flush } from '../test-utils';
import { toChartTime } from '../charttime';

const { api, chart, series, createChart } = vi.hoisted(() => {
  const series = {
    setData: vi.fn(), attachPrimitive: vi.fn(), createPriceLine: vi.fn(),
    priceScale: () => ({ applyOptions: vi.fn() }),
    coordinateToPrice: vi.fn(() => 100), priceToCoordinate: vi.fn(() => 50),
  };
  const chart = {
    addSeries: vi.fn(() => series), applyOptions: vi.fn(), remove: vi.fn(),
    panes: vi.fn(() => Array.from({ length: 4 }, () => ({ setHeight: vi.fn() }))),
    timeScale: () => ({
      fitContent: vi.fn(), subscribeVisibleLogicalRangeChange: vi.fn(),
      coordinateToTime: vi.fn(() => 1), timeToCoordinate: vi.fn(() => 10),
      logicalToCoordinate: vi.fn(() => 10), coordinateToLogical: vi.fn(() => 1),
    }),
    subscribeCrosshairMove: vi.fn(), subscribeClick: vi.fn(),
  };
  return {
    api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
    chart, series, createChart: vi.fn(() => chart),
  };
});

vi.mock('../api', () => api);
vi.mock('lightweight-charts', () => ({
  createChart,
  CandlestickSeries: 'candle', BarSeries: 'bar', LineSeries: 'line',
  HistogramSeries: 'hist', createSeriesMarkers: vi.fn(() => ({ setMarkers: vi.fn() })),
}));

const bars = Array.from({ length: 40 }, (_, i) => ({
  time: `2026-01-${String((i % 28) + 1).padStart(2, '0')}`,
  open: 100 + i, high: 105 + i, low: 95 + i, close: 102 + i, volume: 1000 + i,
}));

/** A stored horizontal line, in the true-UTC form the API returns. */
const HLINE = { id: 7, kind: 'hline', p1: 150.5, t1: null, t2: null, p2: null, label: null };
/** A stored trendline, whose endpoints must cross the timezone boundary. */
const TREND = {
  id: 8, kind: 'trendline', p1: 100, p2: 140,
  t1: Date.UTC(2026, 0, 5) / 1000, t2: Date.UTC(2026, 0, 20) / 1000, label: null,
};

/** The DrawingsPrimitive instance handed to the price series. */
const attached = () => series.attachPrimitive.mock.calls[0][0];

const button = (container, text) =>
  [...container.querySelectorAll('button')].find((b) => b.textContent.trim() === text);

async function mount(drawings = []) {
  api.get.mockResolvedValue({ drawings });
  const view = render(<PriceChart bars={bars} events={[]} interval="1d" ticker="AAPL" />);
  await flush();
  return view;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('the primitive handoff', () => {
  it('attaches exactly one drawings primitive to the price series', async () => {
    const { unmount } = await mount();
    expect(series.attachPrimitive).toHaveBeenCalledTimes(1);
    unmount();
  });

  it('hands the primitive live readers of the drawing state, not a snapshot', async () => {
    // The primitive is constructed inside the chart effect but reads drawings
    // through these two callbacks. If they ever stop seeing current state, lines
    // render stale or vanish, and nothing throws.
    const { unmount } = await mount([HLINE]);
    // `_getDrawings`/`_getSelectedId` are where DrawingsPrimitive stores the two
    // callbacks it was constructed with. Read deliberately: that storage IS the
    // contract under test, and mocking the primitive to capture the constructor
    // arguments instead would stop exercising the real class.
    const primitive = attached();
    expect(typeof primitive._getDrawings).toBe('function');
    expect(typeof primitive._getSelectedId).toBe('function');
    expect(primitive._getDrawings()).toHaveLength(1);
    expect(primitive._getDrawings()[0].id).toBe(7);
    expect(primitive._getSelectedId()).toBeNull();
    unmount();
  });

  it('shifts stored endpoints into chart space before the primitive sees them', async () => {
    // Drawings persist as true UTC epochs and render in chart space. Getting
    // this wrong moves every line eight hours along the axis.
    const { unmount } = await mount([TREND]);
    const row = attached()._getDrawings()[0];
    expect(row.t1).toBe(toChartTime(TREND.t1));
    expect(row.t2).toBe(toChartTime(TREND.t2));
    expect(row.p1).toBe(100); // prices are not shifted
    unmount();
  });
});

describe('loading', () => {
  it('asks for the drawings belonging to the ticker it was given', async () => {
    const { unmount } = await mount([HLINE]);
    expect(api.get).toHaveBeenCalledWith('/stock/AAPL/drawings');
    unmount();
  });

  it('renders with no drawings when the fetch fails, rather than breaking the chart', async () => {
    api.get.mockRejectedValue(new Error('backend down'));
    const view = render(<PriceChart bars={bars} events={[]} interval="1d" ticker="AAPL" />);
    await flush();
    expect(attached()._getDrawings()).toEqual([]);
    expect(view.container.querySelector('.chart-wrap')).not.toBeNull();
    view.unmount();
  });
});

describe('the pan/zoom handshake', () => {
  it('switches the chart drag off while a drawing tool is active', async () => {
    // The canvas would otherwise fight the cursor for the gesture. This is the
    // drawing half reaching into the chart half — the second of the two edges
    // across this boundary.
    const { container, unmount } = await mount();
    chart.applyOptions.mockClear();

    click(button(container, 'Trendline'));
    expect(chart.applyOptions).toHaveBeenCalledWith(
      { handleScroll: false, handleScale: false });
    unmount();
  });

  it('gives the drag back when the cursor tool is reselected', async () => {
    const { container, unmount } = await mount();
    click(button(container, 'Trendline'));
    chart.applyOptions.mockClear();

    click(button(container, 'Cursor'));
    expect(chart.applyOptions).toHaveBeenCalledWith(
      { handleScroll: true, handleScale: true });
    unmount();
  });
});

describe('teardown', () => {
  it('removes the chart when the component unmounts', async () => {
    const { unmount } = await mount();
    unmount();
    expect(chart.remove).toHaveBeenCalled();
  });
});
