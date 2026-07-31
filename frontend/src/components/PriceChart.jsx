import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  CandlestickSeries,
  BarSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
} from 'lightweight-charts';
import { smaSeries, rsiSeries, macdSeries } from '../indicators';

const toDateStr = (t) => {
  if (typeof t === 'string') return t;
  if (typeof t === 'number') return new Date(t * 1000).toISOString().slice(0, 10);
  return `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`;
};

const NEWS_WINDOW_DAYS = 3;
const CHART_TYPES = [
  ['candles', 'Candles'],
  ['line', 'Line'],
  ['ohlc', 'OHLC'],
];
const MA_CONFIG = [
  [10, '#60a5fa'],
  [20, '#f0b90b'],
  [50, '#c084fc'],
];
const OVERLAY_OPTS = { priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };

const fmtVol = (v) => {
  if (v == null) return '—';
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
  return String(Math.round(v));
};

export default function PriceChart({ bars, news }) {
  const containerRef = useRef(null);
  const [popup, setPopup] = useState(null); // {x, date, items}
  const [hoverBar, setHoverBar] = useState(null);
  const [chartType, setChartType] = useState('candles');
  const [show, setShow] = useState({ ma: true, volume: true, rsi: true, macd: false });

  useEffect(() => {
    if (!containerRef.current || !bars.length) return;

    const intraday = typeof bars[0]?.time === 'number';
    const height = 430 + (show.rsi ? 100 : 0) + (show.macd ? 100 : 0);
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
      crosshair: { mode: 0 },
      timeScale: {
        borderColor: 'rgba(120,140,160,0.2)',
        timeVisible: intraday,
        secondsVisible: false,
      },
      rightPriceScale: { borderColor: 'rgba(120,140,160,0.2)' },
    });

    // main price series (selected type)
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

    // moving-average overlays
    if (show.ma) {
      for (const [period, color] of MA_CONFIG) {
        const data = smaSeries(bars, period);
        if (!data.length) continue;
        chart.addSeries(LineSeries, { color, lineWidth: 1.5, ...OVERLAY_OPTS }).setData(data);
      }
    }

    // volume/turnover histogram overlaid at the bottom of the main pane
    if (show.volume) {
      const vol = chart.addSeries(HistogramSeries, {
        priceScaleId: 'vol',
        priceFormat: { type: 'volume' },
        ...OVERLAY_OPTS,
      });
      chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      vol.setData(
        bars.map((b) => ({
          time: b.time,
          value: b.volume ?? 0,
          color: b.close >= b.open ? 'rgba(46,189,133,0.3)' : 'rgba(246,70,93,0.3)',
        }))
      );
    }

    // indicator panes below the price pane
    let paneIdx = 1;
    if (show.rsi) {
      const rsi = chart.addSeries(
        LineSeries,
        { color: '#f0b90b', lineWidth: 1.5, priceLineVisible: false, title: 'RSI 14' },
        paneIdx
      );
      rsi.setData(rsiSeries(bars));
      for (const [price, color] of [[70, 'rgba(246,70,93,0.45)'], [30, 'rgba(46,189,133,0.45)']]) {
        rsi.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
      }
      try { chart.panes()[paneIdx].setHeight(95); } catch { /* pane API optional */ }
      paneIdx += 1;
    }
    if (show.macd) {
      const { macd, signal, hist } = macdSeries(bars);
      if (macd.length) {
        chart.addSeries(HistogramSeries, { ...OVERLAY_OPTS }, paneIdx).setData(hist);
        chart
          .addSeries(LineSeries, { color: '#3b82f6', lineWidth: 1.5, priceLineVisible: false, title: 'MACD' }, paneIdx)
          .setData(macd);
        chart
          .addSeries(LineSeries, { color: '#f0b90b', lineWidth: 1, ...OVERLAY_OPTS }, paneIdx)
          .setData(signal);
        try { chart.panes()[paneIdx].setHeight(95); } catch { /* pane API optional */ }
        paneIdx += 1;
      }
    }

    chart.timeScale().fitContent();

    // small gold dots above bars on dates that have news (one per date)
    const newsDates = new Set(news.map((n) => n.date));
    const seenDates = new Set();
    const markers = [];
    for (const b of bars) {
      const d = toDateStr(b.time);
      if (newsDates.has(d) && !seenDates.has(d)) {
        seenDates.add(d);
        markers.push({
          time: b.time,
          position: 'aboveBar',
          color: '#f0b90b',
          shape: 'circle',
          size: 0.4,
        });
      }
    }
    createSeriesMarkers(series, markers);

    const volByTime = new Map(bars.map((b) => [String(b.time), b.volume]));
    const onMove = (param) => {
      if (!param.time || !param.point) {
        setPopup(null);
        setHoverBar(null);
        return;
      }
      const date = toDateStr(param.time);
      const barData = param.seriesData.get(series);
      setHoverBar(
        barData ? { date, volume: volByTime.get(String(param.time)), ...barData } : null
      );

      const hovered = new Date(date).getTime();
      const items = news.filter((n) => {
        if (!n.date) return false;
        const diff = Math.abs(new Date(n.date).getTime() - hovered);
        return diff <= NEWS_WINDOW_DAYS * 86400_000;
      });
      setPopup(items.length ? { x: param.point.x, date, items: items.slice(0, 3) } : null);
    };
    chart.subscribeCrosshairMove(onMove);

    const resize = () =>
      chart.applyOptions({ width: containerRef.current.clientWidth });
    resize();
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      chart.remove();
    };
  }, [bars, news, chartType, show]);

  const toggle = (key) => setShow((s) => ({ ...s, [key]: !s[key] }));

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
            <button
              key={key}
              className={`seg ${show[key] ? 'active' : ''}`}
              onClick={() => toggle(key)}
            >
              {label}
            </button>
          ))}
        </span>
        {show.ma && (
          <span className="ma-legend">
            {MA_CONFIG.map(([p, color]) => (
              <span key={p} className="ma-chip">
                <span className="ma-swatch" style={{ background: color }} />
                MA{p}
              </span>
            ))}
          </span>
        )}
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
        {popup && (
          <div
            className="news-popup"
            style={{ left: Math.min(popup.x, (containerRef.current?.clientWidth ?? 400) - 340) }}
          >
            <div className="news-popup-date">News near {popup.date}</div>
            {popup.items.map((n, i) => (
              <a key={i} href={n.url} target="_blank" rel="noreferrer" className="news-item">
                <span className="news-meta">
                  <span className={`news-tag ${n.category}`}>
                    {n.category === 'macro' ? 'MACRO' : 'COMPANY'}
                  </span>
                  {n.date} · {n.publisher || 'news'}
                </span>
                {n.title}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
