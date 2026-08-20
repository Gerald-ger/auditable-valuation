import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart,
  CandlestickSeries,
  BarSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
} from 'lightweight-charts';
import { smaSeries, rsiSeries, macdSeries, rollingSdBand, windowSpan } from '../indicators';
import { toChartTime, drawingEpoch, drawingChartTime } from '../charttime';
import { eventStamp, groupEventsByBar, toDateStr } from '../events';
import { DrawingsPrimitive, snapToBar } from '../drawingPrimitive';
import { get, post, patch, del } from '../api';

// Operates on chart-space time, so the date shown on the axis, the date used to
// group event markers and the date in the hover legend cannot disagree.
const CHART_TYPES = [
  ['candles', 'Candles'],
  ['line', 'Line'],
  ['ohlc', 'OHLC'],
];
// Moving averages, in BARS — the charting convention. What each spans in time
// depends on the interval, which the legend names rather than leaves implied.
const MA_CONFIG = [
  [10, '#60a5fa'],
  [20, '#f0b90b'],
  [50, '#c084fc'],
];
const RSI_PERIOD = 14;
const MACD_FAST = 12;
const MACD_SLOW = 26;
const MACD_SIGNAL = 9;
// Dispersion band. 20 bars deliberately matches MA20 above, so the band is
// centred on a line the chart already draws instead of implying a second,
// invisible average. Only the edges are drawn for the same reason.
// Neutral grey on purpose: the MA colours mark lines you are meant to read as
// levels, and this is context rather than a level.
const SD_PERIOD = 20;
const SD_K = 2;
const SD_COLOR = 'rgba(148, 163, 184, 0.55)';
// Wheel gesture. The pan step is a share of the visible window rather than a
// bar count, so one notch moves the same *proportion* whether the chart holds
// 126 bars or 2,385 — a fixed bar count crawls on a max chart and leaps on a
// three-month one. Divided by 100 because a wheel notch is ~100 deltaY.
const WHEEL_PAN_FRACTION = 0.15;
const WHEEL_ZOOM_STEP = 0.9;

// lightweight-charts PriceScaleMode: 0 normal, 1 logarithmic, 2 percentage
const SCALE_MODES = [
  ['Lin', 0, 'Linear price scale'],
  ['Log', 1, 'Logarithmic: equal % moves get equal vertical distance'],
  ['%', 2, 'Percentage change from the first visible bar'],
];

/**
 * Open the chart on the window that was *requested*, not on everything it holds.
 *
 * `/history` prepends up to 50 bars of lead-in so MA50, RSI and MACD exist at
 * the left edge instead of starting a third of the way in. Those bars are real
 * and stay scrollable — the series is given all of them, and panning left walks
 * into the run-up. What they must not do is widen the range: a plain
 * `fitContent()` would show 175 bars under a button labelled "6M", which is the
 * one thing the caller did not ask for.
 *
 * Falls back to `fitContent()` when there is no lead-in, which is not a special
 * case bolted on — `1d`, `5d` and `max` are served without one by design, and a
 * company listed inside the window gets none either.
 */
function fitDisplay(chart, warmup, total) {
  if (!chart) return;
  const ts = chart.timeScale();
  // half-bar padding on each side, which is what fitContent does at the edges
  if (warmup > 0 && total > warmup) ts.setVisibleLogicalRange({ from: warmup - 0.5, to: total - 0.5 });
  else ts.fitContent();
}

/**
 * Marker categories, most-significant first. When several events land on one
 * bar the dot takes the colour of the highest-priority one, so an earnings
 * release is never hidden behind an insider filing.
 */
const EVENT_TYPES = [
  ['earnings', 'Earnings', '#2ebd85'],
  ['material', '8-K event', '#c084fc'],
  ['company', 'Company news', '#3b82f6'],
  ['macro', 'Macro news', '#f0b90b'],
  ['insider', 'Insider', '#8b98a5'],
];
const EVENT_COLOR = Object.fromEntries(EVENT_TYPES.map(([k, , c]) => [k, c]));
const EVENT_LABEL = Object.fromEntries(EVENT_TYPES.map(([k, l]) => [k, l]));
// Insider filings are the bulk of the SEC feed (217 of 278 for AAPL) and say
// little about price, so they start hidden rather than burying the chart.
const DEFAULT_TYPES = { earnings: true, material: true, company: true, macro: true, insider: false };

const OVERLAY_OPTS = { priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };

const fmtVol = (v) => {
  if (v == null) return '—';
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
  return String(Math.round(v));
};

const dominantType = (items) =>
  EVENT_TYPES.find(([key]) => items.some((i) => i.category === key))?.[0] ?? 'company';

export default function PriceChart({
  bars: rawBars = [], events, filingsSupported = true, interval = '1d', ticker = '',
  warmupBars = 0,
}) {
  // Shift once, here, so every downstream consumer — the series, the volume
  // pane, event grouping, the crosshair legend — works in one time space.
  const bars = useMemo(
    () => rawBars.map((b) => ({ ...b, time: toChartTime(b.time) })),
    [rawBars],
  );
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const markersRef = useRef(null);
  const groupsRef = useRef(new Map());
  // The element that goes fullscreen: toolbars and chart together, because a
  // chart you cannot change the interval of is not much use full screen.
  const panelRef = useRef(null);

  const [chartEpoch, setChartEpoch] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  // One switch for two behaviours that mean the same thing to a reader: the
  // crosshair sticking to OHLC values, and a drawing endpoint landing on one.
  // Splitting them would mean explaining why the pointer snaps and the line
  // does not.
  const [magnet, setMagnet] = useState(true);
  // Read by the construction effect, which must not *depend* on `magnet`: a
  // dependency there would rebuild the chart — and discard the reader's pan and
  // zoom — every time the toggle was pressed. The effect below applies the
  // change to the live chart instead.
  const magnetRef = useRef(magnet);
  magnetRef.current = magnet;
  const [hoverBar, setHoverBar] = useState(null);
  // Where the cursor is, so the OHLC readout can follow it instead of sitting
  // in a corner the eye has to travel to.
  const [hoverAt, setHoverAt] = useState(null); // {x, y}
  // The moving end of a half-placed trendline, in chart space.
  const [preview, setPreview] = useState(null);
  const previewRef = useRef(null);
  previewRef.current = preview;
  // Whether a drawing is under the pointer, which is the only thing the cursor
  // shape needs that CSS cannot work out for itself.
  const [hovering, setHovering] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [hoverEvents, setHoverEvents] = useState(null); // {x, date, items} — preview only
  const [pinned, setPinned] = useState(null); // {x, date, items} — clickable
  const [chartType, setChartType] = useState('candles');
  const [scaleMode, setScaleMode] = useState(0);
  // sd defaults off: it is new, and a band that appears unannounced on a chart
  // people already read would be a change of meaning rather than an addition.
  const [show, setShow] = useState({ ma: true, volume: true, rsi: true, macd: false, sd: false });
  const [types, setTypes] = useState(DEFAULT_TYPES);

  // ── drawings ──────────────────────────────────────────────────────
  // State holds the **stored** form — integer UTC epochs, exactly what the API
  // returns — and `chartDrawings` below converts to chart space for rendering.
  // It was the other way round until 2026-08-20, converting once at load, which
  // sent date strings to an integer column and placed a drawing nowhere after a
  // change of period.
  const [drawings, setDrawings] = useState([]);
  const [tool, setTool] = useState('cursor');
  const [selectedId, setSelectedId] = useState(null);
  const [pending, setPending] = useState(null); // first click of a trendline
  const drawingsRef = useRef(drawings);
  const selectedRef = useRef(selectedId);
  const primitiveRef = useRef(null);
  selectedRef.current = selectedId;

  // Which representation this series addresses its x-axis in. Read from the bars
  // rather than from `interval`, so it follows the data even if the two disagree.
  const intraday = typeof bars[0]?.time === 'number';

  /**
   * The drawings in chart space, derived rather than stored.
   *
   * `drawings` state holds exactly what the API holds — integer epochs — and the
   * conversion happens here, on every render that changes the series. It used to
   * happen once at load, which meant a drawing fetched on the 1-year chart kept
   * daily-shaped times after switching to 5-day and was placed nowhere.
   */
  const chartDrawings = useMemo(() => drawings.map((d) => ({
    ...d,
    t1: drawingChartTime(d.t1, intraday),
    t2: drawingChartTime(d.t2, intraday),
  })), [drawings, intraday]);
  drawingsRef.current = chartDrawings;
  // The stored form, for the persistence calls, which must never send chart space.
  const storedRef = useRef(drawings);
  storedRef.current = drawings;

  useEffect(() => {
    if (!ticker) return;
    let live = true;
    get(`/stock/${ticker}/drawings`)
      .then((r) => { if (live) setDrawings(r.drawings ?? []); })
      .catch(() => { if (live) setDrawings([]); });
    setSelectedId(null);
    setPending(null);
    return () => { live = false; };
  }, [ticker]);

  const allGroups = useMemo(() => groupEventsByBar(bars, events ?? []), [bars, events]);
  const visibleGroups = useMemo(
    () =>
      allGroups
        .map((g) => ({ ...g, items: g.items.filter((i) => types[i.category]) }))
        .filter((g) => g.items.length),
    [allGroups, types],
  );
  const available = useMemo(() => {
    const counts = {};
    for (const g of allGroups) for (const i of g.items) counts[i.category] = (counts[i.category] ?? 0) + 1;
    return counts;
  }, [allGroups]);

  // ── chart construction ────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || !bars.length) return;

    /**
     * How tall the chart should be right now.
     *
     * Normally the sum of the panes that are switched on. Full screen it is
     * whatever the row is given instead — the panel is a flex column there and
     * `.chart-wrap` takes the remaining space, so the height follows the screen
     * rather than a constant that would leave a band of empty page under it.
     *
     * `clientHeight` can be 0 for a frame or two after entering fullscreen,
     * before layout settles; falling back to the stacked height keeps the chart
     * from collapsing in that window.
     *
     * Declared inside the effect deliberately. As a component-scope function it
     * is rebuilt every render, so it would have to join this effect's
     * dependencies — and this effect *recreates the chart*, which would throw
     * away the reader's pan and zoom on any state change at all.
     */
    const chartHeight = () => {
      const stacked =
        370 + (show.volume ? 115 : 0) + (show.rsi ? 100 : 0) + (show.macd ? 100 : 0);
      // This panel specifically, not "something on the page is fullscreen": the
      // flex height below only exists under `.chart-panel:fullscreen`, so if a
      // different element went fullscreen the parent would still be auto-height
      // and measuring it would pin the chart to whatever it already was.
      if (document.fullscreenElement !== panelRef.current) return stacked;
      return containerRef.current?.parentElement?.clientHeight || stacked;
    };

    const intraday = typeof bars[0]?.time === 'number';
    const chart = createChart(containerRef.current, {
      height: chartHeight(),
      layout: {
        background: { color: 'transparent' },
        textColor: '#9fb0c3',
        panes: { separatorColor: 'rgba(120,140,160,0.2)' },
      },
      grid: {
        vertLines: { color: 'rgba(120,140,160,0.08)' },
        horzLines: { color: 'rgba(120,140,160,0.08)' },
      },
      // magnet snaps the crosshair to OHLC values instead of floating between
      // them; toggleable since 2026-08-20, because it is the wrong mode for
      // reading the price at an arbitrary point rather than at a bar
      crosshair: { mode: magnetRef.current ? 1 : 0 },
      // Both wheel behaviours off: the library maps a *vertical* wheel to zoom
      // only (`deltaY` -> zoomTime, gated on handleScale.mouseWheel) and pans
      // on `deltaX` alone, so "wheel pans" cannot be expressed in its options.
      // Done by hand below instead, and doing half of it here would mean two
      // handlers fighting over the same gesture.
      handleScale: { mouseWheel: false },
      handleScroll: { mouseWheel: false },
      timeScale: {
        borderColor: 'rgba(120,140,160,0.2)',
        timeVisible: intraday,
        secondsVisible: false,
        rightOffset: 6, // breathing room so the newest marker is not clipped
      },
      rightPriceScale: { borderColor: 'rgba(120,140,160,0.2)', mode: scaleMode },
    });
    chartRef.current = chart;
    markersRef.current = null;

    let series;
    if (chartType === 'line') {
      series = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2 });
      series.setData(bars.map((b) => ({ time: b.time, value: b.close })));
    } else if (chartType === 'ohlc') {
      series = chart.addSeries(BarSeries, {
        upColor: '#2ebd85',
        downColor: '#f6465d',
        thinBars: false,
      });
      series.setData(bars);
    } else {
      series = chart.addSeries(CandlestickSeries, {
        upColor: '#2ebd85',
        downColor: '#f6465d',
        wickUpColor: '#2ebd85',
        wickDownColor: '#f6465d',
        borderVisible: false,
      });
      series.setData(bars);
    }
    seriesRef.current = series;

    // drawings live on the price series so they pan and zoom with it
    const primitive = new DrawingsPrimitive({
      getDrawings: () => drawingsRef.current,
      getSelectedId: () => selectedRef.current,
      getPreview: () => previewRef.current,
    });
    series.attachPrimitive(primitive);
    primitiveRef.current = primitive;

    if (show.ma) {
      for (const [period, color] of MA_CONFIG) {
        // period is in BARS, so the line is as smooth as the bars are fine and
        // starts `period` bars in — there is no warm-up history behind the left
        // edge, which is the one visible difference from a vendor chart
        const data = smaSeries(bars, period);
        if (!data.length) continue;
        chart.addSeries(LineSeries, { color, lineWidth: 1.5, ...OVERLAY_OPTS }).setData(data);
      }
    }

    // Both edges share one period with MA20, so they start on the same bar and
    // the band cannot drift half a bar away from the line it is centred on.
    if (show.sd) {
      const { upper, lower } = rollingSdBand(bars, SD_PERIOD, SD_K);
      for (const data of [upper, lower]) {
        if (!data.length) continue;
        chart
          .addSeries(LineSeries, { color: SD_COLOR, lineWidth: 1, ...OVERLAY_OPTS })
          .setData(data);
      }
    }

    let paneIdx = 1;
    // Volume gets its own pane and its own visible axis. Overlaid on the price
    // pane it shared the frame with the price scale, so 53M volume bars sat
    // beside axis labels reading ~310 and were read against the wrong scale.
    if (show.volume) {
      const vol = chart.addSeries(
        HistogramSeries,
        { priceFormat: { type: 'volume' }, priceLineVisible: false, title: 'Volume' },
        paneIdx,
      );
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.15, bottom: 0.02 } });
      vol.setData(
        bars.map((b) => ({
          time: b.time,
          value: b.volume ?? 0,
          color: b.close >= b.open ? 'rgba(46,189,133,0.55)' : 'rgba(246,70,93,0.55)',
        })),
      );
      try {
        // tall enough for the axis to render intermediate ticks — at ~85px
        // only the last-value badge fits, which is what made volume unreadable
        chart.panes()[paneIdx].setHeight(110);
      } catch { /* pane API optional */ }
      paneIdx += 1;
    }
    if (show.rsi) {
      const rsi = chart.addSeries(
        LineSeries,
        { color: '#f0b90b', lineWidth: 1.5, priceLineVisible: false, title: `RSI ${RSI_PERIOD}` },
        paneIdx,
      );
      rsi.setData(rsiSeries(bars, RSI_PERIOD));
      for (const [price, color] of [[70, 'rgba(246,70,93,0.45)'], [30, 'rgba(46,189,133,0.45)']]) {
        rsi.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
      }
      try {
        chart.panes()[paneIdx].setHeight(95);
      } catch { /* pane API optional */ }
      paneIdx += 1;
    }
    if (show.macd) {
      const { macd, signal, hist } = macdSeries(bars, MACD_FAST, MACD_SLOW, MACD_SIGNAL);
      if (macd.length) {
        chart.addSeries(HistogramSeries, { ...OVERLAY_OPTS }, paneIdx).setData(hist);
        chart
          .addSeries(LineSeries, { color: '#3b82f6', lineWidth: 1.5, priceLineVisible: false, title: 'MACD' }, paneIdx)
          .setData(macd);
        chart
          .addSeries(LineSeries, { color: '#f0b90b', lineWidth: 1, ...OVERLAY_OPTS }, paneIdx)
          .setData(signal);
        try {
          chart.panes()[paneIdx].setHeight(95);
        } catch { /* pane API optional */ }
        paneIdx += 1;
      }
    }

    fitDisplay(chart, warmupBars, bars.length);

    const volByTime = new Map(bars.map((b) => [String(b.time), b.volume]));
    const onMove = (param) => {
      if (!param.time || !param.point) {
        setHoverBar(null);
        setHoverAt(null);
        setHoverEvents(null);
        return;
      }
      const date = toDateStr(param.time);
      const barData = param.seriesData.get(series);
      setHoverAt(param.point);
      setHoverBar(barData ? { date, volume: volByTime.get(String(param.time)), ...barData } : null);
      // Exact bar lookup — every event is snapped onto a bar, so the dot and the
      // preview can no longer disagree about which dates have events.
      const group = groupsRef.current.get(String(param.time));
      setHoverEvents(group ? { x: param.point.x, date: group.date, items: group.items } : null);
    };
    chart.subscribeCrosshairMove(onMove);

    // Click to pin. The hover preview is pointer-events:none so it cannot be
    // clicked; the pinned panel is the interactive one. This is what stopped
    // the flashing: previously the popup sat under the cursor, stole the
    // mousemove, the chart reported "cursor left", the popup unmounted, the
    // chart got the cursor back — repeating forever.
    chart.subscribeClick((param) => {
      if (!param.time || !param.point) return;
      const group = groupsRef.current.get(String(param.time));
      setPinned(group ? { x: param.point.x, date: group.date, items: group.items } : null);
    });

    const resize = () => chart.applyOptions({
      width: containerRef.current.clientWidth,
      height: chartHeight(),
    });
    resize();
    window.addEventListener('resize', resize);

    /**
     * Resize from the box actually changing, not from an event that precedes it.
     *
     * Entering or leaving fullscreen fires no `resize`. Listening to
     * `fullscreenchange` and measuring — even a frame later, which is what this
     * did first — reads the layout while the browser is still reflowing back to
     * the page, so on the way *out* the chart kept its fullscreen width and the
     * proportions stayed wrong until something else rebuilt it. Clicking MA
     * appeared to fix it because that recreates the chart.
     *
     * A ResizeObserver on the parent has no timing to get wrong: it reports the
     * size after layout, whatever caused it — fullscreen, window, or a panel
     * opening beside it. It also cannot feed back on itself, and that is worth
     * stating since observing an element whose size you then set usually can:
     * windowed, `chartHeight()` returns a constant, so the second pass is a
     * no-op; fullscreen, `.chart-wrap` is `flex: 1` and takes its height from
     * the panel rather than from the chart inside it.
     *
     * Guarded because jsdom has no ResizeObserver — the same gap that makes this
     * suite mock the chart wholesale. `fullscreenchange` stays as the fallback
     * for that case only.
     */
    const wrap = containerRef.current.parentElement;
    let observer = null;
    if (typeof ResizeObserver !== 'undefined' && wrap) {
      observer = new ResizeObserver(() => resize());
      observer.observe(wrap);
    }
    const onFullscreenChange = () => requestAnimationFrame(resize);
    document.addEventListener('fullscreenchange', onFullscreenChange);
    const onDblClick = () => fitDisplay(chart, warmupBars, bars.length);
    const el = containerRef.current;
    el.addEventListener('dblclick', onDblClick);

    /**
     * Wheel pans; Ctrl (or Cmd) + wheel zooms.
     *
     * Both library wheel behaviours are off, so this owns the gesture outright
     * — including `preventDefault`, which the library only calls on the events
     * it handles. Without it the page would scroll under the chart.
     *
     * The trade was chosen deliberately: while the pointer is over the chart the
     * page can no longer be scrolled with the wheel. That is how charting tools
     * behave and it is the cost of the gesture doing something useful here.
     *
     * `deltaX` is folded in for trackpads, which send horizontal scroll for the
     * same intent.
     */
    const onWheel = (e) => {
      const ts = chart.timeScale();
      const range = ts.getVisibleLogicalRange?.();
      if (!range) return;
      if (e.cancelable) e.preventDefault();
      const span = range.to - range.from;
      if (e.ctrlKey || e.metaKey) {
        const factor = e.deltaY > 0 ? 1 / WHEEL_ZOOM_STEP : WHEEL_ZOOM_STEP;
        const mid = (range.from + range.to) / 2;
        const half = (span / 2) * factor;
        ts.setVisibleLogicalRange({ from: mid - half, to: mid + half });
        return;
      }
      // in bars, so one notch moves the same share of the window at any zoom
      const step = (e.deltaY + e.deltaX) * WHEEL_PAN_FRACTION * span / 100;
      ts.setVisibleLogicalRange({ from: range.from + step, to: range.to + step });
    };
    el.addEventListener('wheel', onWheel, { passive: false });

    setChartEpoch((e) => e + 1);
    return () => {
      window.removeEventListener('resize', resize);
      document.removeEventListener('fullscreenchange', onFullscreenChange);
      observer?.disconnect();
      el.removeEventListener('wheel', onWheel);
      el.removeEventListener('dblclick', onDblClick);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      markersRef.current = null;
      primitiveRef.current = null;
    };
  }, [bars, chartType, show, scaleMode, warmupBars]);

  // ── markers, updated without rebuilding the chart ─────────────────
  // Kept in its own effect so toggling a filter does not recreate the chart and
  // throw away the zoom/pan the user set up.
  useEffect(() => {
    groupsRef.current = new Map(visibleGroups.map((g) => [String(g.time), g]));
    if (!seriesRef.current) return;
    const markers = visibleGroups.map((g) => ({
      time: g.time,
      position: 'aboveBar',
      color: EVENT_COLOR[dominantType(g.items)],
      shape: 'circle',
      size: g.items.length > 2 ? 1.3 : 0.9,
      text: g.items.length > 1 ? String(g.items.length) : undefined,
    }));
    if (markersRef.current) markersRef.current.setMarkers(markers);
    else markersRef.current = createSeriesMarkers(seriesRef.current, markers);
  }, [visibleGroups, chartEpoch]);

  // a pinned panel for a bar that got filtered away would dangle
  useEffect(() => {
    if (pinned && !groupsRef.current.has(String(pinned.time ?? ''))) {
      const still = visibleGroups.find((g) => g.date === pinned.date);
      setPinned(still ? { ...pinned, items: still.items } : null);
    }
  }, [visibleGroups]); // eslint-disable-line react-hooks/exhaustive-deps

  // Windows count bars, so an indicator is missing only when the chart holds
  // fewer bars than its window — which now takes a very short series rather
  // than merely a short period.
  const unavailable = [];
  if (show.ma && bars.length) {
    const missing = MA_CONFIG.filter(([p]) => bars.length <= p);
    if (missing.length) unavailable.push(missing.map(([p]) => `MA${p}`).join('/'));
  }
  if (show.sd && bars.length && bars.length <= SD_PERIOD) unavailable.push(`±${SD_K} SD(${SD_PERIOD})`);
  if (show.rsi && bars.length && bars.length <= RSI_PERIOD) unavailable.push(`RSI(${RSI_PERIOD})`);
  if (show.macd && bars.length && bars.length <= MACD_SLOW) {
    unavailable.push(`MACD(${MACD_FAST},${MACD_SLOW},${MACD_SIGNAL})`);
  }

  // ── drawing interaction ───────────────────────────────────────────
  // Raw pointer events on the container rather than the chart's click
  // subscription, because dragging a handle needs move/up as well as down —
  // and while a tool is active or a handle is held, the chart's own pan/zoom
  // has to be switched off or the canvas fights the cursor for the gesture.
  useEffect(() => {
    const el = containerRef.current;
    const chart = chartRef.current;
    const primitive = primitiveRef.current;
    if (!el || !chart || !primitive || !ticker) return undefined;

    // Spelled out per sub-option rather than as a bare boolean. `handleScale:
    // true` sets *every* member including `mouseWheel`, which would re-enable
    // the library's own wheel-to-zoom and silently undo the pan gesture — the
    // first time the reader picked a tool and put it back.
    const armed = tool !== 'cursor';
    chart.applyOptions({
      handleScroll: { mouseWheel: false, pressedMouseMove: !armed,
                      horzTouchDrag: !armed, vertTouchDrag: !armed },
      handleScale: { mouseWheel: false, pinch: !armed,
                     axisPressedMouseMove: !armed, axisDoubleClickReset: !armed },
    });

    let drag = null; // {id, handle}

    const localPoint = (e) => {
      const r = el.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };

    const persistMove = (d) => {
      // `d` comes from `storedRef`, which holds the API's own shape, so the
      // times need no conversion here. They did while state was kept in chart
      // space, and `fromChartTime` passed date strings through unchanged — which
      // is how a daily-chart drag sent a string to an integer column.
      patch(`/stock/${ticker}/drawings/${d.id}`, {
        t1: d.t1, p1: d.p1, t2: d.t2, p2: d.p2,
      }).catch(() => {}); // a failed save must not break the gesture
    };

    // Every placed or dragged point goes through here, so the crosshair and the
    // line it is used to draw agree about where a bar is.
    const at = (x, y) => {
      const raw = primitive.toDataPoint(x, y);
      return magnet ? snapToBar(bars, raw.time, raw.price) : raw;
    };

    const onDown = (e) => {
      const { x, y } = localPoint(e);
      const { time, price } = at(x, y);

      if (tool === 'cursor') {
        const hit = primitive.hitTest(x, y);
        setSelectedId(hit?.id ?? null);
        if (hit) {
          drag = hit;
          setDragging(true);
          chart.applyOptions({
            handleScroll: { mouseWheel: false, pressedMouseMove: false },
            handleScale: { mouseWheel: false, pinch: false },
          });
          e.preventDefault();
        }
        primitive.update();
        return;
      }
      if (price == null) return;

      if (tool === 'hline') {
        post(`/stock/${ticker}/drawings`, { kind: 'hline', p1: price })
          .then(({ id }) => setDrawings((cur) => [...cur, { id, kind: 'hline', p1: price }]))
          .catch(() => {});
        setTool('cursor');
        return;
      }
      if (tool === 'trendline') {
        if (time == null) return;
        if (!pending) {
          setPending({ t1: time, p1: price });
          return;
        }
        const body = {
          kind: 'trendline',
          t1: drawingEpoch(pending.t1), p1: pending.p1,
          t2: drawingEpoch(time), p2: price,
        };
        // Refused rather than posted when either end will not resolve to an
        // epoch. The API answers 422 for that and the catch below is silent, so
        // without this the line would simply never appear and say nothing.
        if (body.t1 == null || body.t2 == null) return;
        post(`/stock/${ticker}/drawings`, body)
          .then(({ id }) => setDrawings((cur) => [...cur, { id, ...body }]))
          .catch(() => {});
        setPending(null);
        setPreview(null);
        setTool('cursor');
      }
    };

    const onMove = (e) => {
      const { x, y } = localPoint(e);

      if (!drag) {
        // Two things that only need the pointer's position: what the cursor
        // should look like, and where the half-placed trendline currently ends.
        if (tool === 'cursor') {
          setHovering(primitive.hitTest(x, y) != null);
        } else if (pending) {
          const p = at(x, y);
          setPreview(p.time == null || p.price == null
            ? null
            : { t1: pending.t1, p1: pending.p1, t2: p.time, p2: p.price });
        }
        return;
      }

      const { time, price } = at(x, y);
      if (price == null) return;
      // Captured before the updater, and that is the whole point.
      //
      // `drag` is a mutable closure variable that `onUp` sets to null, and React
      // runs a functional update during the *render* phase rather than when it
      // is queued. Release the pointer quickly enough after a move and the order
      // becomes: move queues the update -> up nulls `drag` -> React runs the
      // updater -> `drag.id` throws **during render**, which the error boundary
      // catches as "This panel failed to render". Intermittent by nature: it
      // needs the release to beat the render, which is exactly what the end of a
      // fast drag looks like.
      //
      // Reading a mutable variable inside an updater makes the update impure —
      // it depends on when React chooses to run it. Closing over the value
      // instead makes the queued update mean what it meant when it was queued.
      const target = drag;
      // stored form: chart time converted on the way in, exactly as a freshly
      // placed point is
      const epoch = drawingEpoch(time);
      setDrawings((cur) => cur.map((d) => {
        if (d.id !== target.id) return d;
        if (d.kind === 'hline') return { ...d, p1: price };
        if (target.handle === 0) return { ...d, t1: epoch ?? d.t1, p1: price };
        if (target.handle === 1) return { ...d, t2: epoch ?? d.t2, p2: price };
        return d;
      }));
      primitive.update();
    };

    const onUp = () => {
      if (drag) {
        const moved = storedRef.current.find((d) => d.id === drag.id);
        if (moved) persistMove(moved);
        drag = null;
        setDragging(false);
        // Restored as objects, not `true`: `handleScale: true` would re-enable
        // `mouseWheel` and hand the wheel back to the library's zoom, quietly
        // undoing the pan gesture the first time anyone dragged a line.
        chart.applyOptions({
          handleScroll: { mouseWheel: false, pressedMouseMove: true },
          handleScale: { mouseWheel: false, pinch: true },
        });
      }
    };

    // Esc abandons a half-drawn trendline and clears a selection. Without it the
    // only way out of a pending line was to switch tool, which is not where
    // anyone looks for "cancel".
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setPending(null);
        setPreview(null);
        setSelectedId(null);
        setTool('cursor');
      }
    };

    el.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('keydown', onKey);
    return () => {
      el.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('keydown', onKey);
    };
  }, [tool, pending, ticker, chartEpoch, magnet, bars]);

  // repaint whenever the drawing set, the selection or the preview changes
  useEffect(() => { primitiveRef.current?.update(); }, [drawings, selectedId, preview]);

  // Applied rather than rebuilt: recreating the chart to change one option
  // would throw away the pan and zoom the reader had set up.
  useEffect(() => {
    chartRef.current?.applyOptions({ crosshair: { mode: magnet ? 1 : 0 } });
  }, [magnet, chartEpoch]);

  // ── fullscreen ────────────────────────────────────────────────────
  // `fullscreenchange` is the source of truth, not the button: Esc, the browser
  // menu and F11 all leave without going through it, and a flag set on click
  // would then disagree with the screen.
  useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement === panelRef.current);
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);

  const toggleFullscreen = () => {
    if (document.fullscreenElement) {
      document.exitFullscreen?.();
      return;
    }
    // Rejects when the gesture is not trusted or the browser refuses; nothing to
    // recover, and throwing here would take the toolbar down with it.
    panelRef.current?.requestFullscreen?.().catch(() => {});
  };

  function deleteSelected() {
    if (selectedId == null) return;
    del(`/stock/${ticker}/drawings/${selectedId}`).catch(() => {});
    setDrawings((cur) => cur.filter((d) => d.id !== selectedId));
    setSelectedId(null);
  }

  function clearDrawings() {
    del(`/stock/${ticker}/drawings`).catch(() => {});
    setDrawings([]);
    setSelectedId(null);
  }

  const toggle = (key) => setShow((s) => ({ ...s, [key]: !s[key] }));
  const toggleType = (key) => setTypes((t) => ({ ...t, [key]: !t[key] }));

  const zoom = (factor) => {
    const ts = chartRef.current?.timeScale();
    const range = ts?.getVisibleLogicalRange();
    if (!range) return;
    const mid = (range.from + range.to) / 2;
    const half = ((range.to - range.from) / 2) * factor;
    ts.setVisibleLogicalRange({ from: mid - half, to: mid + half });
  };

  const totalShown = visibleGroups.reduce((n, g) => n + g.items.length, 0);

  // What the pointer says it will do if you press now. Ordered by precedence:
  // a live drag beats a hover, and an armed tool beats both.
  const cursorMode = dragging ? 'grabbing'
    : tool !== 'cursor' ? 'draw'
      : hovering ? 'grab' : 'default';

  return (
    <div className="chart-panel" ref={panelRef}>
      <div className="chart-toolbar">
        <span className="seg-group">
          {CHART_TYPES.map(([key, label]) => (
            <button
              key={key}
              className={`seg ${chartType === key ? 'active' : ''}`}
              onClick={() => setChartType(key)}
            >
              {label}
            </button>
          ))}
        </span>
        <span className="seg-group">
          {[
            ['ma', 'MA', null],
            ['volume', 'Volume', null],
            ['rsi', 'RSI', null],
            ['macd', 'MACD', null],
            // Named for what it is. "Bollinger Bands" would carry a
            // trading-signal claim; these lines only say how far price sits
            // from its own recent mean.
            ['sd', '±2 SD',
              `Price ±${SD_K} standard deviations of the last ${SD_PERIOD} bars, ` +
              `centred on MA${SD_PERIOD}. A measure of how wide this name has been ` +
              `trading lately, not a signal: about 88% of closes sit inside, so a ` +
              `touch happens roughly twice a month and means little on its own.`],
          ].map(([key, label, title]) => (
            <button
              key={key}
              title={title ?? undefined}
              className={`seg ${show[key] ? 'active' : ''}`}
              onClick={() => toggle(key)}
            >
              {label}
            </button>
          ))}
        </span>
        <span className="seg-group">
          {SCALE_MODES.map(([label, mode, title]) => (
            <button
              key={label}
              title={title}
              className={`seg ${scaleMode === mode ? 'active' : ''}`}
              onClick={() => setScaleMode(mode)}
            >
              {label}
            </button>
          ))}
        </span>
        <span className="seg-group">
          <button className="seg" title="Zoom in" onClick={() => zoom(0.7)}>＋</button>
          <button className="seg" title="Zoom out" onClick={() => zoom(1.4)}>－</button>
          <button
            className="seg"
            title={warmupBars > 0
              ? 'Back to the selected range (or double-click the chart). Pan left for the indicator run-up.'
              : 'Fit all data (or double-click the chart)'}
            onClick={() => fitDisplay(chartRef.current, warmupBars, bars.length)}
          >
            Reset
          </button>
        </span>
        <span className="seg-group">
          <button
            className={`seg ${magnet ? 'active' : ''}`}
            title={magnet
              ? 'Magnet on: the crosshair sticks to open/high/low/close, and a line you draw lands on one. Click to read prices at any point instead.'
              : 'Magnet off: the crosshair and new lines follow the pointer exactly.'}
            onClick={() => setMagnet((m) => !m)}
          >
            Magnet
          </button>
          <button
            className={`seg ${fullscreen ? 'active' : ''}`}
            title={fullscreen ? 'Leave full screen (Esc)' : 'Full screen'}
            onClick={toggleFullscreen}
          >
            {fullscreen ? 'Exit' : 'Full screen'}
          </button>
        </span>
        {show.ma && (
          <span className="ma-legend">
            {MA_CONFIG.map(([p, color]) => (
              <span
                key={p}
                className={`ma-chip ${bars.length <= p ? 'ma-chip-unavailable' : ''}`}
                title={
                  bars.length <= p
                    ? `Needs ${p} bars; this chart has ${bars.length}.`
                    : `${p}-bar average ≈ ${windowSpan(p, interval)} at ${interval} bars`
                }
              >
                <span className="ma-swatch" style={{ background: color }} />
                MA{p}
              </span>
            ))}
            {/* MA50 is 50 minutes here and 50 days on the 5y chart. Naming the
                unit in the legend is what stops the same label meaning two
                things without saying so. */}
            <span
              className="ma-basis"
              title={`Indicator windows count bars. At ${interval} bars, MA50 spans ≈ ${windowSpan(50, interval)}.`}
            >
              bars @ {interval}
            </span>
          </span>
        )}
      </div>

      {unavailable.length > 0 && (
        <div className="chart-note">
          {unavailable.join(', ')} need{unavailable.length === 1 ? 's' : ''} more bars than this
          chart holds ({bars.length}). Windows are measured in bars, so a longer period, or a
          finer interval, fills them.
        </div>
      )}

      <div className="chart-toolbar draw-toolbar">
        <span className="filter-label">Draw</span>
        <span className="seg-group">
          {[
            ['cursor', 'Cursor', 'Select and drag existing lines'],
            ['trendline', 'Trendline', 'Click the start, then the end'],
            ['hline', 'Horiz line', 'Click once to place a price level'],
          ].map(([key, label, hint]) => (
            <button
              key={key}
              className={`seg ${tool === key ? 'active' : ''}`}
              title={hint}
              onClick={() => { setTool(key); setPending(null); setPreview(null); }}
            >
              {label}
            </button>
          ))}
        </span>
        <button className="seg" disabled={selectedId == null} onClick={deleteSelected}>
          Delete
        </button>
        <button className="seg" disabled={!drawings.length} onClick={clearDrawings}>
          Clear all
        </button>
        <span className="chart-note draw-hint">
          {pending
            ? 'Click the end point to finish the trendline.'
            : tool === 'trendline'
              ? 'Click the start point.'
              : tool === 'hline'
                ? 'Click a price level.'
                : `${drawings.length} saved · your lines are stored and read by the AI outlook and chat.`}
        </span>
      </div>

      <div className="chart-toolbar event-filter">
        <span className="filter-label">Markers</span>
        {EVENT_TYPES.map(([key, label, color]) => {
          const count = available[key] ?? 0;
          return (
            <button
              key={key}
              className={`chip ${types[key] && count ? 'on' : ''}`}
              disabled={!count}
              onClick={() => toggleType(key)}
              title={count ? `${count} ${label} events in range` : `No ${label} events for this ticker`}
            >
              <span className="chip-dot" style={{ background: color }} />
              {label}
              <span className="chip-count">{count}</span>
            </button>
          );
        })}
        <span className="chart-note filter-note">
          {totalShown} marker{totalShown === 1 ? '' : 's'} shown · click a dot to open its stories
          {!filingsSupported && ' · SEC filings are US-only, so this ticker has news markers only'}
        </span>
      </div>

      <div className="chart-wrap">
        {hoverBar && (
          <div
            className="chart-legend chart-legend-follow"
            /* Follows the pointer, offset up-left of it so the readout is not
               under the hand. Flips to the other side within 300px of the right
               edge and below the cursor near the top, so it never leaves the
               pane — the reason both offsets are computed rather than fixed. */
            style={hoverAt ? {
              left: Math.max(4, Math.min(hoverAt.x + 14,
                (containerRef.current?.clientWidth ?? 600) - 300)),
              top: Math.max(4, hoverAt.y - 30),
            } : undefined}
          >
            {hoverBar.date}
            {hoverBar.open !== undefined ? (
              <>
                {' '}O {hoverBar.open?.toFixed(2)} H {hoverBar.high?.toFixed(2)} L{' '}
                {hoverBar.low?.toFixed(2)} C {hoverBar.close?.toFixed(2)}
              </>
            ) : (
              <> {hoverBar.value?.toFixed(2)}</>
            )}
            {' '}V {fmtVol(hoverBar.volume)}
          </div>
        )}
        <div ref={containerRef} className={`chart-canvas cursor-${cursorMode}`} />

        {hoverEvents && !pinned && (
          <div
            className="news-preview"
            style={{ left: Math.min(hoverEvents.x, (containerRef.current?.clientWidth ?? 400) - 320) }}
          >
            <div className="news-popup-date">
              {hoverEvents.items.length} event{hoverEvents.items.length === 1 ? '' : 's'} ·{' '}
              {hoverEvents.date} (click to open)
            </div>
            {hoverEvents.items.slice(0, 3).map((n, i) => (
              <div key={i} className="news-preview-row">
                <span className="chip-dot" style={{ background: EVENT_COLOR[n.category] }} />
                {n.title}
              </div>
            ))}
            {hoverEvents.items.length > 3 && (
              <div className="news-preview-row muted-note">+{hoverEvents.items.length - 3} more…</div>
            )}
          </div>
        )}

        {pinned && (
          <div
            className="news-popup"
            style={{ left: Math.min(pinned.x, (containerRef.current?.clientWidth ?? 400) - 340) }}
          >
            <div className="news-popup-date">
              {pinned.date} · {pinned.items.length} event{pinned.items.length === 1 ? '' : 's'}
              <button className="popup-close" onClick={() => setPinned(null)} title="Close">
                ✕
              </button>
            </div>
            <div className="news-popup-scroll">
              {pinned.items.map((n, i) => {
                const stamp = eventStamp(n);
                return (
                  <a key={i} href={n.url} target="_blank" rel="noreferrer" className="news-item">
                    <span className="news-meta">
                      <span className="news-tag" style={{ color: EVENT_COLOR[n.category] }}>
                        {EVENT_LABEL[n.category]?.toUpperCase()}
                      </span>
                      <span title={stamp.title}>{stamp.text}</span> · {n.publisher || 'news'}
                    </span>
                    {n.title}
                  </a>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
