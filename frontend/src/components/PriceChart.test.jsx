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
import { act } from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import PriceChart from './PriceChart';
import { render, click, flush } from '../test-utils';
import { toChartTime } from '../charttime';

const { api, chart, series, createChart, timeScaleApi } = vi.hoisted(() => {
  const series = {
    setData: vi.fn(), createPriceLine: vi.fn(),
    priceScale: () => ({ applyOptions: vi.fn() }),
    coordinateToPrice: vi.fn(() => 100), priceToCoordinate: vi.fn(() => 50),
    /**
     * Wires the primitive up, which a bare `vi.fn()` did not.
     *
     * `DrawingsPrimitive.toDataPoint` returns `{time: null, price: null}` until
     * `attached()` gives it the chart and series — so with an inert mock every
     * click resolved to a null price and `onDown` returned before doing
     * anything. Nothing failed, because nothing exercised the gesture; the
     * moment a test did, it failed for this reason instead of the real one.
     */
    attachPrimitive: vi.fn((p) => p.attached({
      chart, series, requestUpdate: () => {},
    })),
  };
  /**
   * The `ITimeScaleApi` surface this component reaches for, defined once.
   *
   * It was three hand-maintained copies until 2026-08-20, and they drifted:
   * `DrawingsPrimitive.screenShapes` calls `width()` on every hit test, none of
   * the three had it, and the TypeError fired inside a `pointermove` listener.
   * Unhandled rather than failed, so vitest printed "137 passed" and *exited 1*
   * — green-looking locally, red on CI runs #38 and #39. Adding it in three
   * places would have fixed those two runs and left the next method to drift.
   */
  const timeScaleApi = (extra = {}) => ({
    fitContent: vi.fn(), subscribeVisibleLogicalRangeChange: vi.fn(),
    coordinateToTime: vi.fn(() => 1), timeToCoordinate: vi.fn(() => 10),
    logicalToCoordinate: vi.fn(() => 10), coordinateToLogical: vi.fn(() => 1),
    width: vi.fn(() => 600),
    ...extra,
  });
  const chart = {
    addSeries: vi.fn(() => series), applyOptions: vi.fn(), remove: vi.fn(),
    panes: vi.fn(() => Array.from({ length: 4 }, () => ({ setHeight: vi.fn() }))),
    timeScale: () => timeScaleApi(),
    subscribeCrosshairMove: vi.fn(), subscribeClick: vi.fn(),
  };
  return {
    /**
     * Every one of these returns a promise in `../api`, and so must the double.
     * `vi.fn()` returns undefined, so `persistMove`'s `.catch(() => {})` threw
     * the moment a test actually dragged something — inside a `pointerup`
     * listener, i.e. unhandled, so vitest counted the test as passing and still
     * exited 1. Individual tests override with `mockResolvedValue`; this is the
     * floor, so a call nobody stubbed cannot take the run down.
     */
    api: {
      get: vi.fn(() => Promise.resolve({})),
      post: vi.fn(() => Promise.resolve({ id: 1 })),
      patch: vi.fn(() => Promise.resolve({})),
      del: vi.fn(() => Promise.resolve({})),
    },
    chart, series, createChart: vi.fn(() => chart), timeScaleApi,
  };
});

vi.mock('../api', () => api);
vi.mock('lightweight-charts', () => ({
  createChart,
  CandlestickSeries: 'candle', BarSeries: 'bar', LineSeries: 'line',
  HistogramSeries: 'hist', createSeriesMarkers: vi.fn(() => ({ setMarkers: vi.fn() })),
  // Mirrors the library's own enum. Spelled out because the component imports
  // it by name rather than passing 0/1/3 — which is what let the toolbar
  // promise open/high/low/close while the chart was given `Magnet`, the mode
  // that snaps to the close alone.
  CrosshairMode: { Normal: 0, Magnet: 1, Hidden: 2, MagnetOHLC: 3 },
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

async function mount(drawings = [], props = {}) {
  api.get.mockResolvedValue({ drawings });
  const view = render(
    <PriceChart bars={bars} events={[]} interval="1d" ticker="AAPL" {...props} />);
  await flush();
  return view;
}

/**
 * Put the panel into the state the *browser* reports, not a React flag.
 *
 * `PriceChart` derives `fullscreen` from `document.fullscreenElement` on a
 * `fullscreenchange` event, deliberately: Esc, F11 and the browser menu all
 * leave full screen without going through the button. jsdom implements neither,
 * so the property is shadowed and the event dispatched by hand.
 */
const enterFullscreen = (container) => {
  const panel = container.querySelector('.chart-panel');
  Object.defineProperty(document, 'fullscreenElement', { value: panel, configurable: true });
  act(() => { document.dispatchEvent(new Event('fullscreenchange')); });
};

beforeEach(() => {
  vi.clearAllMocks();
  // Shared across files through the jsdom `document`, so a test that entered
  // full screen must not leave every later one believing it is still there.
  Object.defineProperty(document, 'fullscreenElement', { value: null, configurable: true });
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

  it('gives the primitive endpoints in the representation the series uses', async () => {
    /**
     * Drawings persist as integer UTC epochs; a chart addresses its x-axis in
     * whatever type its *bars* carry. These fixture bars are date strings — the
     * daily case, which is `6mo` through `max` — so the endpoints must arrive as
     * date strings too. Handing that series an epoch places the line nowhere,
     * because `timeToCoordinate` cannot match a number against string times.
     *
     * This asserted `toChartTime(TREND.t1)` until 2026-08-20, i.e. the epoch
     * plus the display offset. That is right only for an intraday series, and it
     * passed while trendlines were in fact unplaceable on every daily range.
     */
    const { unmount } = await mount([TREND]);
    const row = attached()._getDrawings()[0];
    expect(row.t1).toBe('2026-01-05');
    expect(row.t2).toBe('2026-01-20');
    expect(typeof row.t1).toBe(typeof bars[0].time);
    expect(row.p1).toBe(100); // prices are not converted
    unmount();
  });

  it('shifts endpoints by the display offset on an intraday series', async () => {
    // The other branch: numeric bar times mean the drawing is shifted into
    // GMT+8 like every other timestamp the chart shows.
    const intradayBars = bars.map((b, i) => ({ ...b, time: 1767225600 + i * 3600 }));
    api.get.mockResolvedValue({ drawings: [TREND] });
    const view = render(
      <PriceChart bars={intradayBars} events={[]} interval="1h" ticker="AAPL" />);
    await flush();
    expect(attached()._getDrawings()[0].t1).toBe(toChartTime(TREND.t1));
    view.unmount();
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
  /** The last handleScroll/handleScale pair applied to the chart. */
  const lastHandles = () => {
    const call = [...chart.applyOptions.mock.calls]
      .reverse().find(([o]) => o.handleScroll || o.handleScale);
    return call?.[0];
  };

  it('switches the chart drag off while a drawing tool is active', async () => {
    // The canvas would otherwise fight the cursor for the gesture. This is the
    // drawing half reaching into the chart half — the second of the two edges
    // across this boundary.
    const { container, unmount } = await mount();
    chart.applyOptions.mockClear();

    click(button(container, 'Trendline'));
    expect(lastHandles().handleScroll.pressedMouseMove).toBe(false);
    expect(lastHandles().handleScale.pinch).toBe(false);
    unmount();
  });

  it('gives the drag back when the cursor tool is reselected', async () => {
    const { container, unmount } = await mount();
    click(button(container, 'Trendline'));
    chart.applyOptions.mockClear();

    click(button(container, 'Cursor'));
    expect(lastHandles().handleScroll.pressedMouseMove).toBe(true);
    expect(lastHandles().handleScale.pinch).toBe(true);
    unmount();
  });

  it('never hands the mouse wheel back to the library', async () => {
    /**
     * The regression these two tests could not have caught in their old form.
     *
     * They asserted `{handleScroll: true, handleScale: true}`, and a bare `true`
     * sets **every** sub-option — including `mouseWheel`. Since the wheel now
     * pans by hand, that would have re-enabled the library's wheel-to-zoom on
     * top of it, so the first person to pick a drawing tool and put it back
     * would have silently got two handlers fighting over one gesture.
     *
     * Asserted across every applied pair rather than the last, because it has to
     * hold in each of the three states: armed, released, and after a drag.
     */
    const { container, unmount } = await mount();
    click(button(container, 'Trendline'));
    click(button(container, 'Cursor'));

    const pairs = chart.applyOptions.mock.calls
      .map(([o]) => o).filter((o) => o.handleScroll || o.handleScale);
    expect(pairs.length).toBeGreaterThan(0);
    for (const o of pairs) {
      expect(o.handleScroll?.mouseWheel ?? false).toBe(false);
      expect(o.handleScale?.mouseWheel ?? false).toBe(false);
    }
    unmount();
  });
});

describe('placing a drawing', () => {
  /**
   * The gesture itself, which nothing here exercised until 2026-08-20.
   *
   * Every other test in this file drives buttons and the primitive seam, so a
   * `ReferenceError` inside the `pointerdown` handler was invisible to all of
   * them — the suite stayed green while the drawing tools did nothing at all.
   * `onDown` resolves the click to a data point *before* it branches on the
   * tool, so one throw there disables placing a line and selecting one alike,
   * and the chart simply looks inert.
   */
  const press = (container, { x = 120, y = 80 } = {}) => {
    const canvas = container.querySelector('.chart-canvas');
    canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 600, height: 400 });
    act(() => {
      canvas.dispatchEvent(new MouseEvent('pointerdown', {
        bubbles: true, cancelable: true, clientX: x, clientY: y,
      }));
    });
  };

  it('creates a horizontal line on one click', async () => {
    api.post.mockResolvedValue({ id: 99 });
    const { container, unmount } = await mount();

    click(button(container, 'Horiz line'));
    press(container);

    expect(api.post).toHaveBeenCalledWith(
      '/stock/AAPL/drawings', expect.objectContaining({ kind: 'hline' }));
    unmount();
  });

  it('takes two clicks to make a trendline, and posts on the second', async () => {
    api.post.mockResolvedValue({ id: 98 });
    const { container, unmount } = await mount();

    click(button(container, 'Trendline'));
    press(container, { x: 100, y: 60 });
    expect(api.post).not.toHaveBeenCalled(); // first click only arms it

    press(container, { x: 300, y: 200 });
    expect(api.post).toHaveBeenCalledWith(
      '/stock/AAPL/drawings', expect.objectContaining({ kind: 'trendline' }));
    unmount();
  });

  it('lets the cursor tool resolve a click without throwing', async () => {
    // Same handler, same first line: the point resolution runs before the tool
    // is looked at, so a fault there takes selection down with placement.
    const { container, unmount } = await mount([HLINE]);
    press(container);
    expect(api.post).not.toHaveBeenCalled();
    unmount();
  });
});

describe('dragging a drawing', () => {
  const at = (container, x, y, type) => {
    const canvas = container.querySelector('.chart-canvas');
    canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 600, height: 400 });
    const target = type === 'pointerdown' ? canvas : window;
    target.dispatchEvent(new MouseEvent(type, {
      bubbles: true, cancelable: true, clientX: x, clientY: y,
    }));
  };

  it('survives the pointer being released before React runs the update', async () => {
    /**
     * "This panel failed to render — Cannot read properties of null (reading
     * 'id')", reported from real use and reproduced here.
     *
     * `drag` is a mutable closure variable and `onUp` nulls it. React runs a
     * functional update during the **render** phase, not when it is queued, so a
     * release that beats the render leaves the updater dereferencing null — and
     * because it happens while rendering, the error boundary catches it and
     * replaces the whole panel rather than losing one gesture.
     *
     * Batching the move and the release into one `act` is what makes the race
     * deterministic: React flushes at the end of the block, by which time `onUp`
     * has already run. Without the capture this throws; with it the drag simply
     * ends.
     *
     * Pre-existing — the same shape is at HEAD, predating the drawing work.
     */
    api.get.mockResolvedValue({ drawings: [TREND] });
    const { container, unmount } = await mount([TREND]);

    // grab the trendline: the mocked series puts every price at y=50, so a
    // press anywhere on it hits a handle
    act(() => { at(container, 10, 50, 'pointerdown'); });

    /**
     * Several moves before the release, which is what makes this bite.
     *
     * React computes the *first* update on an empty queue eagerly, to see
     * whether it can bail out — so a single move runs its updater immediately
     * and the race cannot be observed. A second queued update takes the
     * deferred path, which is the ordinary case in the real app where
     * `setHovering`, `setPreview` and the marker effects are all in flight.
     */
    expect(() => {
      act(() => {
        at(container, 110, 70, 'pointermove');
        at(container, 120, 80, 'pointermove');
        at(container, 130, 90, 'pointermove');
        at(container, 130, 90, 'pointerup');
      });
    }).not.toThrow();

    unmount();
  });
});

describe('the magnet toggle', () => {
  it('applies the crosshair mode to the live chart instead of rebuilding it', async () => {
    /**
     * The rebuild is the thing to avoid: recreating the chart to change one
     * option would discard whatever pan and zoom the reader had set up. This is
     * why `magnet` is read through a ref in the construction effect rather than
     * listed as a dependency of it.
     */
    const { container, unmount } = await mount();
    const before = createChart.mock.calls.length;
    chart.applyOptions.mockClear();

    click(button(container, 'Magnet'));
    expect(chart.applyOptions).toHaveBeenCalledWith({
      crosshair: { mode: 0, horzLine: { visible: true, labelVisible: true } },
    });

    // 3 is `CrosshairMode.MagnetOHLC`, not 1 (`Magnet`). The difference is the
    // one the toolbar's own tooltip has always described: `Magnet` sticks the
    // crosshair to an OHLC series' **close** only, while the button says it
    // "sticks to open/high/low/close". Measured against the installed
    // lightweight-charts 5.2.0 typings, which document exactly that split.
    //
    // The price line is hidden with the magnet on, and `labelVisible` with it.
    // Hiding only the line would move the defect to the price axis rather than
    // remove it: the label is drawn at the same snapped price, so it would go
    // on reporting a moving average while the line stopped saying so.
    click(button(container, 'Magnet'));
    expect(chart.applyOptions).toHaveBeenCalledWith({
      crosshair: { mode: 3, horzLine: { visible: false, labelVisible: false } },
    });
    expect(createChart.mock.calls.length).toBe(before);
    unmount();
  });
});

describe('full screen', () => {
  it('asks for the panel, so the toolbars go with the chart', async () => {
    const request = vi.fn(() => Promise.resolve());
    Element.prototype.requestFullscreen = request;
    const { container, unmount } = await mount();

    click(button(container, 'Full screen'));
    expect(request).toHaveBeenCalled();
    // the element it was called on has to be the panel, not the canvas: a
    // fullscreen chart with no interval buttons is not much use
    expect(request.mock.instances[0].className).toContain('chart-panel');
    unmount();
  });

  it('survives a browser that refuses the request', async () => {
    // Rejects when the gesture is not trusted. An unhandled rejection here
    // would take the toolbar down with it.
    Element.prototype.requestFullscreen = vi.fn(() => Promise.reject(new Error('denied')));
    const { container, unmount } = await mount();
    click(button(container, 'Full screen'));
    await flush();
    expect(button(container, 'Full screen')).toBeTruthy();
    unmount();
  });
});

describe('the full-screen control bar', () => {
  /**
   * Which chart you are looking at — the stock and the range — as opposed to how
   * it is drawn. Both controls live on the page, and the page is not rendered
   * while a panel is full screen: the fullscreen element is the panel, and the
   * top layer holds nothing else. So going full screen used to mean giving up
   * the ability to change stock or period until you came back out.
   */
  const PROPS = {
    periods: ['1d', '5d', '1y'], period: '5d', onPeriod: () => {},
    saved: ['MSFT'], onTicker: () => {},
  };

  it('keeps both controls off the windowed panel, where the page already has them', async () => {
    const { container, unmount } = await mount([], PROPS);
    expect(container.querySelector('.fullscreen-bar')).toBeNull();
    unmount();
  });

  it('offers the period picker and the ticker box once full screen', async () => {
    const { container, unmount } = await mount([], PROPS);
    enterFullscreen(container);

    const bar = container.querySelector('.fullscreen-bar');
    expect(bar).not.toBeNull();
    expect([...bar.querySelectorAll('.period-picker button')].map((b) => b.textContent))
      .toEqual(['1d', '5d', '1y']);
    // marked to whatever the caller says is current, not to an internal copy
    expect(bar.querySelector('.period-picker button.active').textContent).toBe('5d');
    expect(bar.querySelector('.search-box input').value).toBe('AAPL');
    unmount();
  });

  it('reports a period choice upward rather than keeping it', async () => {
    // The period decides which bars are fetched, which only the caller can do.
    const onPeriod = vi.fn();
    const { container, unmount } = await mount([], { ...PROPS, onPeriod });
    enterFullscreen(container);

    click([...container.querySelectorAll('.fullscreen-bar .period-picker button')]
      .find((b) => b.textContent === '1y'));
    expect(onPeriod).toHaveBeenCalledWith('1y');
    unmount();
  });

  it('renders neither control when the caller cannot act on it', async () => {
    // A picker whose choice goes nowhere is worse than no picker: it looks live.
    const { container, unmount } = await mount([], {});
    enterFullscreen(container);
    const bar = container.querySelector('.fullscreen-bar');
    expect(bar.querySelector('.period-picker')).toBeNull();
    expect(bar.querySelector('.search-box')).toBeNull();
    unmount();
  });
});

describe('the loading badge', () => {
  it('marks the chart busy instead of the caller replacing it', async () => {
    /**
     * The panel IS the fullscreen element, so swapping it for a "Loading…"
     * placeholder removes it from the document and the browser leaves full
     * screen — measured in Chrome on 2026-08-20: one click on a period button
     * and `.chart-panel` was gone from the DOM. The previous chart stays up and
     * this badge says a newer one is coming.
     */
    const { container, unmount } = await mount([], { loading: true });
    expect(container.querySelector('.chart-loading')).not.toBeNull();
    // and the chart is still there underneath, which is the whole point
    expect(container.querySelector('.chart-canvas')).not.toBeNull();
    unmount();
  });

  it('shows nothing when idle', async () => {
    const { container, unmount } = await mount();
    expect(container.querySelector('.chart-loading')).toBeNull();
    unmount();
  });
});

describe('changing ticker without remounting', () => {
  it('drops the previous name\'s drawings rather than showing them on the new chart', async () => {
    /**
     * `App` stopped keying this subtree on the ticker on 2026-08-20, because the
     * remount destroyed the fullscreen element and dropped the browser out of
     * full screen. The remount was also what cleared this state for free: without
     * it, AAPL's lines stayed drawn over MSFT's prices until the fetch returned.
     */
    const { rerender, unmount } = await mount([HLINE]);
    expect(attached()._getDrawings()).toHaveLength(1);

    api.get.mockReturnValue(new Promise(() => {})); // in flight, never resolves
    rerender(<PriceChart bars={bars} events={[]} interval="1d" ticker="MSFT" />);
    expect(attached()._getDrawings()).toHaveLength(0);
    unmount();
  });
});

describe('resizing', () => {
  it('watches the box rather than the fullscreen event', async () => {
    /**
     * Leaving fullscreen left the chart at its fullscreen proportions until
     * something else rebuilt it — clicking MA appeared to fix it because that
     * recreates the chart. The cause was measuring on `fullscreenchange`, which
     * fires while the browser is still reflowing back to the page, so
     * `clientWidth` was still the fullscreen width.
     *
     * A ResizeObserver reports the size *after* layout, whatever caused it, so
     * there is no frame count to get wrong. Asserted on the parent, because
     * observing the chart's own element — whose height this then sets — is the
     * arrangement that can feed back on itself.
     */
    const observe = vi.fn();
    globalThis.ResizeObserver = class {
      constructor(cb) { this.cb = cb; }
      observe(el) { observe(el); }
      disconnect() {}
    };
    const { container, unmount } = await mount();
    expect(observe).toHaveBeenCalled();
    expect(observe.mock.calls[0][0]).toBe(container.querySelector('.chart-wrap'));
    unmount();
    delete globalThis.ResizeObserver;
  });

  it('does not measure a container that has gone', async () => {
    /**
     * The fullscreen fallback defers the resize by a frame, and a queued frame
     * outlives the effect that queued it: leave full screen and unmount in the
     * same frame and it ran against a null ref.
     *
     * Driven by taking the frames rather than waiting for them. The throw would
     * happen inside a `requestAnimationFrame` callback, i.e. unhandled — vitest
     * reports that separately from a failure, so a test that merely waited would
     * stay green while the crash happened. Calling the callback here puts it
     * back inside an assertion.
     */
    const frames = [];
    const raf = vi.spyOn(globalThis, 'requestAnimationFrame')
      .mockImplementation((cb) => { frames.push(cb); return 1; });
    const { container, unmount } = await mount();

    enterFullscreen(container); // queues the deferred resize
    unmount();                  // and takes the container with it
    expect(frames.length).toBeGreaterThan(0);
    expect(() => frames.forEach((f) => f(0))).not.toThrow();
    raf.mockRestore();
  });

  it('sets height as well as width, or fullscreen could never change it', async () => {
    const { unmount } = await mount();
    const sized = chart.applyOptions.mock.calls
      .map(([o]) => o).filter((o) => o.width !== undefined);
    expect(sized.length).toBeGreaterThan(0);
    for (const o of sized) expect(o.height).toBeGreaterThan(0);
    unmount();
  });
});

describe('the wheel gesture', () => {
  const wheel = (el, init) => {
    const e = new WheelEvent('wheel', { bubbles: true, cancelable: true, ...init });
    el.dispatchEvent(e);
    return e;
  };
  const canvas = (container) => container.querySelector('.chart-canvas');

  it('pans on a plain wheel and does not let the page scroll', async () => {
    /**
     * The library maps a *vertical* wheel to zoom only and pans on `deltaX`
     * alone, so "wheel pans" cannot be expressed in its options — both are
     * switched off and this owns the gesture, `preventDefault` included. Without
     * that call the page would scroll under the chart, because the library only
     * cancels the events it handles.
     */
    const { container, unmount } = await mount();
    const range = { from: 0, to: 100 };
    const setVisibleLogicalRange = vi.fn();
    chart.timeScale = () => timeScaleApi({
      getVisibleLogicalRange: () => range, setVisibleLogicalRange,
    });

    const e = wheel(canvas(container), { deltaY: 100 });
    expect(e.defaultPrevented).toBe(true);
    const moved = setVisibleLogicalRange.mock.calls.at(-1)[0];
    expect(moved.to - moved.from).toBeCloseTo(100); // width held: panned, not zoomed
    expect(moved.from).toBeGreaterThan(0);
    unmount();
  });

  it('zooms on ctrl+wheel, keeping the window centred', async () => {
    const { container, unmount } = await mount();
    const setVisibleLogicalRange = vi.fn();
    chart.timeScale = () => timeScaleApi({
      getVisibleLogicalRange: () => ({ from: 0, to: 100 }), setVisibleLogicalRange,
    });

    wheel(canvas(container), { deltaY: -100, ctrlKey: true });
    const zoomed = setVisibleLogicalRange.mock.calls.at(-1)[0];
    expect(zoomed.to - zoomed.from).toBeLessThan(100); // narrower: zoomed in
    expect((zoomed.from + zoomed.to) / 2).toBeCloseTo(50); // same centre
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
