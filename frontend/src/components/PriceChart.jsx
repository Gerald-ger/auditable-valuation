import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart,
  CandlestickSeries,
  BarSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
} from 'lightweight-charts';
import { smaSeries, rsiSeries, macdSeries, windowSpan } from '../indicators';
import { toChartTime, fromChartTime } from '../charttime';
import { eventStamp, groupEventsByBar, toDateStr } from '../events';
import { DrawingsPrimitive } from '../drawingPrimitive';
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
// lightweight-charts PriceScaleMode: 0 normal, 1 logarithmic, 2 percentage
const SCALE_MODES = [
  ['Lin', 0, 'Linear price scale'],
  ['Log', 1, 'Logarithmic: equal % moves get equal vertical distance'],
  ['%', 2, 'Percentage change from the first visible bar'],
];

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

  const [chartEpoch, setChartEpoch] = useState(0);
  const [hoverBar, setHoverBar] = useState(null);
  const [hoverEvents, setHoverEvents] = useState(null); // {x, date, items} — preview only
  const [pinned, setPinned] = useState(null); // {x, date, items} — clickable
  const [chartType, setChartType] = useState('candles');
  const [scaleMode, setScaleMode] = useState(0);
  const [show, setShow] = useState({ ma: true, volume: true, rsi: true, macd: false });
  const [types, setTypes] = useState(DEFAULT_TYPES);

  // ── drawings ──────────────────────────────────────────────────────
  // Stored in chart space (GMT+8 shifted) so rendering needs no conversion;
  // converted back to true epochs at the persistence boundary below.
  const [drawings, setDrawings] = useState([]);
  const [tool, setTool] = useState('cursor');
  const [selectedId, setSelectedId] = useState(null);
  const [pending, setPending] = useState(null); // first click of a trendline
  const drawingsRef = useRef(drawings);
  const selectedRef = useRef(selectedId);
  const primitiveRef = useRef(null);
  drawingsRef.current = drawings;
  selectedRef.current = selectedId;

  const toRow = (d) => ({
    id: d.id, kind: d.kind, label: d.label,
    p1: d.p1, p2: d.p2,
    t1: d.t1 == null ? null : toChartTime(d.t1),
    t2: d.t2 == null ? null : toChartTime(d.t2),
  });

  useEffect(() => {
    if (!ticker) return;
    let live = true;
    get(`/stock/${ticker}/drawings`)
      .then((r) => { if (live) setDrawings((r.drawings ?? []).map(toRow)); })
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

    const intraday = typeof bars[0]?.time === 'number';
    const height =
      370 + (show.volume ? 115 : 0) + (show.rsi ? 100 : 0) + (show.macd ? 100 : 0);
    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { color: 'transparent' },
        textColor: '#9fb0c3',
        panes: { separatorColor: 'rgba(120,140,160,0.2)' },
      },
      grid: {
        vertLines: { color: 'rgba(120,140,160,0.08)' },
        horzLines: { color: 'rgba(120,140,160,0.08)' },
      },
      // magnet snaps the crosshair to OHLC values instead of floating between them
      crosshair: { mode: 1 },
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

    chart.timeScale().fitContent();

    const volByTime = new Map(bars.map((b) => [String(b.time), b.volume]));
    const onMove = (param) => {
      if (!param.time || !param.point) {
        setHoverBar(null);
        setHoverEvents(null);
        return;
      }
      const date = toDateStr(param.time);
      const barData = param.seriesData.get(series);
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

    const resize = () => chart.applyOptions({ width: containerRef.current.clientWidth });
    resize();
    window.addEventListener('resize', resize);
    const onDblClick = () => chart.timeScale().fitContent();
    const el = containerRef.current;
    el.addEventListener('dblclick', onDblClick);

    setChartEpoch((e) => e + 1);
    return () => {
      window.removeEventListener('resize', resize);
      el.removeEventListener('dblclick', onDblClick);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      markersRef.current = null;
      primitiveRef.current = null;
    };
  }, [bars, chartType, show, scaleMode]);

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

    const interactive = tool !== 'cursor';
    chart.applyOptions({
      handleScroll: !interactive,
      handleScale: !interactive,
    });

    let drag = null; // {id, handle}

    const localPoint = (e) => {
      const r = el.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };

    const persistMove = (d) => {
      patch(`/stock/${ticker}/drawings/${d.id}`, {
        t1: d.t1 == null ? null : fromChartTime(d.t1),
        p1: d.p1,
        t2: d.t2 == null ? null : fromChartTime(d.t2),
        p2: d.p2,
      }).catch(() => {}); // a failed save must not break the gesture
    };

    const onDown = (e) => {
      const { x, y } = localPoint(e);
      const { time, price } = primitive.toDataPoint(x, y);

      if (tool === 'cursor') {
        const hit = primitive.hitTest(x, y);
        setSelectedId(hit?.id ?? null);
        if (hit) {
          drag = hit;
          chart.applyOptions({ handleScroll: false, handleScale: false });
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
          t1: fromChartTime(pending.t1), p1: pending.p1,
          t2: fromChartTime(time), p2: price,
        };
        post(`/stock/${ticker}/drawings`, body)
          .then(({ id }) => setDrawings((cur) => [...cur,
            { id, kind: 'trendline', t1: pending.t1, p1: pending.p1, t2: time, p2: price }]))
          .catch(() => {});
        setPending(null);
        setTool('cursor');
      }
    };

    const onMove = (e) => {
      if (!drag) return;
      const { x, y } = localPoint(e);
      const { time, price } = primitive.toDataPoint(x, y);
      if (price == null) return;
      setDrawings((cur) => cur.map((d) => {
        if (d.id !== drag.id) return d;
        if (d.kind === 'hline') return { ...d, p1: price };
        if (drag.handle === 0) return { ...d, t1: time ?? d.t1, p1: price };
        if (drag.handle === 1) return { ...d, t2: time ?? d.t2, p2: price };
        return d;
      }));
      primitive.update();
    };

    const onUp = () => {
      if (drag) {
        const moved = drawingsRef.current.find((d) => d.id === drag.id);
        if (moved) persistMove(moved);
        drag = null;
        chart.applyOptions({ handleScroll: true, handleScale: true });
      }
    };

    el.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      el.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [tool, pending, ticker, chartEpoch]);

  // repaint whenever the drawing set or the selection changes
  useEffect(() => { primitiveRef.current?.update(); }, [drawings, selectedId]);

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

  return (
    <div>
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
            ['ma', 'MA'],
            ['volume', 'Volume'],
            ['rsi', 'RSI'],
            ['macd', 'MACD'],
          ].map(([key, label]) => (
            <button key={key} className={`seg ${show[key] ? 'active' : ''}`} onClick={() => toggle(key)}>
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
          <button className="seg" title="Fit all data (or double-click the chart)" onClick={() => chartRef.current?.timeScale().fitContent()}>
            Reset
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
              onClick={() => { setTool(key); setPending(null); }}
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
          <div className="chart-legend">
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
        <div ref={containerRef} />

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
