import { useEffect, useState } from 'react';
import { get, post } from '../api';
import { num, big } from '../format';
import PriceChart from './PriceChart';
import ChatBox from './ChatBox';

const PERIODS = ['1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', 'max'];

export default function TrackerTab({ ticker, aiOnline }) {
  const [quote, setQuote] = useState(null);
  const [bars, setBars] = useState([]);
  const [news, setNews] = useState([]);
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
      get(`/stock/${ticker}/news`),
    ])
      .then(([q, h, n]) => {
        setQuote(q);
        setBars(h);
        setNews(n);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ticker, period]);

  async function generateOutlook() {
    setOutlookBusy(true);
    setOutlook(null);
    try {
      const res = await post(`/ai/predict/${ticker}`);
      setOutlook(res.reply ?? `⚠ ${res.message ?? 'Local AI unavailable.'}`);
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
              <span>52w {num(quote.fifty_two_week_low)}–{num(quote.fifty_two_week_high)}</span>
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
          {loading ? (
            <div className="empty-state loading">Loading…</div>
          ) : (
            <PriceChart bars={bars} news={news} />
          )}
          <div className="chart-note">
            ● gold dots mark dates with news — hover the chart to see the stories behind a move
          </div>
        </div>

        <div className="panel">
          <div className="panel-title">News behind the chart</div>
          {news.length === 0 ? (
            <div className="chart-note">No news available for this ticker.</div>
          ) : (
            <div className="news-list">
              {news.map((n, i) => (
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
              Requires the local AI — install Ollama to enable (see README).
            </div>
          )}
          {outlook && <div className="outlook-text">{outlook}</div>}
        </div>
      </div>

      <ChatBox ticker={ticker} aiOnline={aiOnline} />
    </div>
  );
}
