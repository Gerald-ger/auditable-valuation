import { useEffect, useState } from 'react';
import { get } from './api';
import TrackerTab from './components/TrackerTab';
import ModelsTab from './components/ModelsTab';
import ScorecardTab from './components/ScorecardTab';
import ScreenerTab from './components/ScreenerTab';
import PortfolioTab from './components/PortfolioTab';
import SearchBar from './components/SearchBar';
import ErrorBoundary from './components/ErrorBoundary';
import { pushRecent } from './recents';

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
  const [ticker, setTicker] = useState('AAPL');
  const [aiOnline, setAiOnline] = useState(false);
  // watchlist + holdings, surfaced as one-click chips under the search box
  const [saved, setSaved] = useState([]);

  useEffect(() => {
    const check = () =>
      get('/ai/status')
        .then((s) => setAiOnline(s.online))
        .catch(() => setAiOnline(false));
    check();
    const id = setInterval(check, 30000);
    return () => clearInterval(id);
  }, []);

  // Refetched on tab changes so a position added in the Portfolio tab shows up
  // as a chip without a page reload.
  useEffect(() => {
    get('/portfolio/tickers')
      .then((r) => setSaved(r.tickers ?? []))
      .catch(() => setSaved([]));
  }, [tab]);

  /** Jump from a Screener/Portfolio row straight into that company's scorecard. */
  function openScorecard(t) {
    pushRecent(t);
    setTicker(t);
    setTab('scorecard');
  }

  return (
    <div className="app">
      <header>
        <h1>Stock Analysis Platform</h1>
        {TICKER_TABS.has(tab) && (
          <SearchBar value={ticker} saved={saved} onSelect={setTicker} />
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
        {/* keyed on tab+ticker so navigating away from a failed render resets it
            rather than leaving the boundary stuck on a stale error */}
        <ErrorBoundary key={`${tab}:${ticker}`}>
          {tab === 'tracker' && <TrackerTab ticker={ticker} aiOnline={aiOnline} />}
          {tab === 'models' && <ModelsTab ticker={ticker} />}
          {tab === 'scorecard' && <ScorecardTab ticker={ticker} aiOnline={aiOnline} />}
          {tab === 'screener' && <ScreenerTab onPick={openScorecard} />}
          {tab === 'portfolio' && <PortfolioTab onPick={openScorecard} />}
        </ErrorBoundary>
      </main>
      <footer>
        Data: yfinance (OpenBB adapter ready) · AI: local Ollama · Decision support only —
        not certified financial advice.
      </footer>
    </div>
  );
}
