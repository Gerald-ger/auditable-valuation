import { useEffect, useState } from 'react';
import { get } from './api';
import TrackerTab from './components/TrackerTab';
import ModelsTab from './components/ModelsTab';
import ScorecardTab from './components/ScorecardTab';
import ScreenerTab from './components/ScreenerTab';
import PortfolioTab from './components/PortfolioTab';

const TABS = [
  ['tracker', '📈 Tracker'],
  ['models', '🧮 Financial Models'],
  ['scorecard', '🎯 Scorecard'],
  ['screener', '📊 Screener'],
  ['portfolio', '💼 Portfolio'],
];

// Screener and Portfolio work across many tickers, so the single-ticker box in
// the header does not apply to them.
const TICKER_TABS = new Set(['tracker', 'models', 'scorecard']);

export default function App() {
  const [tab, setTab] = useState('tracker');
  const [input, setInput] = useState('AAPL');
  const [ticker, setTicker] = useState('AAPL');
  const [aiOnline, setAiOnline] = useState(false);

  useEffect(() => {
    const check = () =>
      get('/ai/status')
        .then((s) => setAiOnline(s.online))
        .catch(() => setAiOnline(false));
    check();
    const id = setInterval(check, 30000);
    return () => clearInterval(id);
  }, []);

  function load() {
    const t = input.trim().toUpperCase();
    if (t) setTicker(t);
  }

  /** Jump from a Screener/Portfolio row straight into that company's scorecard. */
  function openScorecard(t) {
    setInput(t);
    setTicker(t);
    setTab('scorecard');
  }

  return (
    <div className="app">
      <header>
        <h1>Stock Analysis Platform</h1>
        {TICKER_TABS.has(tab) && (
          <div className="ticker-box">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && load()}
              placeholder="Ticker — e.g. AAPL, MSFT, 0700.HK"
            />
            <button className="primary" onClick={load}>
              Load
            </button>
          </div>
        )}
        <nav>
          {TABS.map(([key, label]) => (
            <button
              key={key}
              className={tab === key ? 'active' : ''}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === 'tracker' && <TrackerTab ticker={ticker} aiOnline={aiOnline} />}
        {tab === 'models' && <ModelsTab ticker={ticker} />}
        {tab === 'scorecard' && <ScorecardTab ticker={ticker} aiOnline={aiOnline} />}
        {tab === 'screener' && <ScreenerTab onPick={openScorecard} />}
        {tab === 'portfolio' && <PortfolioTab onPick={openScorecard} />}
      </main>
      <footer>
        Data: yfinance (OpenBB adapter ready) · AI: local Ollama · Decision support only —
        not certified financial advice.
      </footer>
    </div>
  );
}
