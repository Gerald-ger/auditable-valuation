import { useEffect, useState } from 'react';
import { get, stream } from '../api';
import { num, big } from '../format';
import PriceChart from './PriceChart';
import { DISPLAY_TZ_LABEL } from '../charttime';
import ChatBox from './ChatBox';

const PERIODS = ['1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', 'max'];

export default function TrackerTab({ ticker, aiOnline, saved = [], onTicker }) {
  const [quote, setQuote] = useState(null);
  const [bars, setBars] = useState([]);
  // interval is chosen by the backend per period (1m for 1d, 1d for 1y, ...).
  // MA/RSI/MACD windows count bars, so it is what says how long they span.
  const [interval, setInterval_] = useState('1d');
  // How many leading bars are lead-in rather than part of the requested range.
  // The chart is given all of them — indicators need the run-up — and opens on
  // the range that was asked for.
  const [warmupBars, setWarmupBars] = useState(0);
  // every datable item (news + SEC filings) for the chart markers; the list
  // below stays headlines-only, which is what "News behind the chart" means
  const [events, setEvents] = useState([]);
  const [filingsSupported, setFilingsSupported] = useState(true);
  const [period, setPeriod] = useState('1y');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [outlook, setOutlook] = useState(null);
  const [outlookBusy, setOutlookBusy] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    setOutlook(null);
    Promise.all([
      get(`/stock/${ticker}/quote`),
      get(`/stock/${ticker}/history?period=${period}`),
      get(`/stock/${ticker}/events`),
    ])
      .then(([q, h, e]) => {
        setQuote(q);
        // guarded: a backend older than the page returns a bare array here,
        // and an undefined `bars` throws inside the chart's render
        setBars(h.bars ?? []);
        setInterval_(h.interval ?? '1d');
        // absent on a backend older than the page, which is the same guard the
        // line above needs and means the same thing: no lead-in, fit everything
        setWarmupBars(h.warmup_bars ?? 0);
        setEvents(e.events);
        setFilingsSupported(e.filings_supported);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ticker, period]);

  async function generateOutlook() {
    setOutlookBusy(true);
    setOutlook('');
    try {
      await stream(`/ai/predict/${ticker}`, {}, (e) => {
        if (e.error) setOutlook(`⚠ ${e.message}`);
        else setOutlook((prev) => (prev ?? '') + e.delta);
      });
    } catch (e) {
      setOutlook(`⚠ ${e.message}`);
    } finally {
      setOutlookBusy(false);
    }
  }

  if (!ticker) return <div className="empty-state">Enter a ticker above to start tracking.</div>;
  if (error) return <div className="error-banner">{error}</div>;

  const change = quote && quote.previous_close ? quote.price - quote.previous_close : null;
  const changePct = change !== null ? (change / quote.previous_close) * 100 : null;
  // filings are chart markers, not headlines — this panel keeps its meaning
  const headlines = events.filter((n) => n.category === 'company' || n.category === 'macro');

  return (
    <div className="tracker-grid">
      <div className="tracker-main">
        {quote && (
          <div className="quote-strip panel">
            <div className="quote-name">
              <span className="quote-ticker">{quote.ticker}</span>
              <span className="quote-long">{quote.name} · {quote.exchange}</span>
            </div>
            <div className="quote-price">
              {num(quote.price)} <span className="quote-ccy">{quote.currency}</span>
              {change !== null && (
                <span className={`quote-change ${change >= 0 ? 'up' : 'down'}`}>
                  {change >= 0 ? '+' : ''}
                  {num(change)} ({changePct.toFixed(2)}%)
                </span>
              )}
            </div>
            <div className="quote-stats">
              <span>Mkt cap {big(quote.market_cap)}</span>
              <span>P/E {num(quote.pe_trailing, 1)}</span>
              <span>52w {num(quote.fifty_two_week_low)}-{num(quote.fifty_two_week_high)}</span>
            </div>
          </div>
        )}

        <div className="panel">
          <div className="panel-title">
            Price history
            <span className="period-picker">
              {PERIODS.map((p) => (
                <button
                  key={p}
                  className={p === period ? 'active' : ''}
                  onClick={() => setPeriod(p)}
                >
                  {p}
                </button>
              ))}
            </span>
          </div>
          {/* Swapped for the placeholder only when there is nothing to show yet.
              A reload with bars already on screen keeps the chart mounted and
              marks it busy instead — the panel is the fullscreen element, so
              unmounting it removes it from the document and the browser leaves
              full screen. Measured 2026-08-20: one click on a period button
              while full screen and `.chart-panel` was gone from the DOM. */}
          {loading && !bars.length ? (
            <div className="empty-state loading">Loading…</div>
          ) : (
            <PriceChart
              bars={bars}
              events={events}
              filingsSupported={filingsSupported}
              interval={interval}
              ticker={ticker}
              warmupBars={warmupBars}
              loading={loading}
              periods={PERIODS}
              period={period}
              onPeriod={setPeriod}
              saved={saved}
              onTicker={onTicker}
            />
          )}
          <div className="chart-note">
            {(bars.length - warmupBars).toLocaleString()} bars at {interval}
            {warmupBars > 0
              ? ` (+${warmupBars} before it, so MA50 reaches the left edge — pan left to see them)`
              : ''} · times in {DISPLAY_TZ_LABEL}
            {interval.endsWith('m') || interval.endsWith('h')
              ? ' (a US session runs 21:30-04:00 and so spans two dates)'
              : ''}{' '}
            {/* Kept in step with the gesture. This said "scroll to zoom" until
                2026-08-20, when the wheel became a pan — a caption describing
                the opposite of what the chart does is worse than none. */}
            · scroll to pan · ctrl+scroll to zoom · drag to pan · double-click to fit
            · hover a dot to preview, click to open its stories
          </div>
        </div>

        <div className="panel">
          <div className="panel-title">News behind the chart</div>
          {headlines.length === 0 ? (
            <div className="chart-note">No news available for this ticker.</div>
          ) : (
            <div className="news-list">
              {headlines.map((n, i) => (
                <a key={i} href={n.url} target="_blank" rel="noreferrer" className="news-row">
                  <span className="news-row-date">{n.date}</span>
                  <span className={`news-tag ${n.category}`}>
                    {n.category === 'macro' ? 'MACRO' : 'COMPANY'}
                  </span>
                  <span className="news-row-title">{n.title}</span>
                  <span className="news-row-pub">{n.publisher}</span>
                </a>
              ))}
            </div>
          )}
        </div>

        <div className="panel">
          <div className="panel-title">
            AI outlook (past · present · future)
            <button className="primary" onClick={generateOutlook} disabled={outlookBusy || !aiOnline}>
              {outlookBusy ? 'Analyzing…' : 'Generate'}
            </button>
          </div>
          {!aiOnline && (
            <div className="ai-offline-note">
              Requires the local AI. Install Ollama to enable (see README).
            </div>
          )}
          {outlook !== null && (
            <div className="outlook-text">
              {outlook || (outlookBusy && 'Analyzing…')}
              {outlookBusy && outlook && <span className="debate-cursor" />}
            </div>
          )}
        </div>
      </div>

      <ChatBox ticker={ticker} aiOnline={aiOnline} />
    </div>
  );
}
