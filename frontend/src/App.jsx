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
  // Backend source changed since it booted. Worth a banner because the symptom
  // is silence: an endpoint added after the server started returns nothing, the
  // panel reading it renders nothing, and that is indistinguishable from a
  // feature never having been built. It cost three separate diagnoses on
  // 2026-08-14, one of them of a panel that was working perfectly.
  const [backendStale, setBackendStale] = useState(false);
  // watchlist + holdings, surfaced as one-click chips under the search box
  const [saved, setSaved] = useState([]);

  // `/health` carries the same AI block `/ai/status` does, plus whether the
  // backend is still running the code on disk — so one poll answers both rather
  // than adding a second timer for the second question.
  useEffect(() => {
    const check = () =>
      get('/health')
        .then((s) => {
          setAiOnline(s.ai?.online ?? false);
          setBackendStale(s.source_changed_since_start === true);
        })
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
        {backendStale && (
          <div className="ai-offline-note">
            <b>The backend is running older code than this project folder.</b> Python
            files changed after the server started, so new fields are missing from
            its responses and any panel that reads one will simply not appear.
            Restart it — <code>-m uvicorn backend.main:app --port 8000</code>
            {' '}— then reload this page.
          </div>
        )}
        {/* `resetKey`, not `key`: navigating away from a failed render still
            clears the boundary, but a healthy subtree is left standing. As a
            `key` this rebuilt everything on every ticker change, which took the
            tracker's chart panel down with it — and that panel is the fullscreen
            element, so changing stock always dropped you out of full screen.

            Models and Scorecard keep the remount as their own `key`, because
            they hold per-ticker working state — DCF overrides, a peer list, a
            generated narrative — that a plain prop change does not reset. The
            tracker refetches everything it shows from `[ticker, period]`, so it
            has nothing to clear. */}
        <ErrorBoundary resetKey={`${tab}:${ticker}`}>
          {tab === 'tracker' && (
            <TrackerTab
              ticker={ticker}
              aiOnline={aiOnline}
              saved={saved}
              onTicker={setTicker}
            />
          )}
          {tab === 'models' && <ModelsTab key={ticker} ticker={ticker} />}
          {tab === 'scorecard' && <ScorecardTab key={ticker} ticker={ticker} aiOnline={aiOnline} />}
          {tab === 'screener' && <ScreenerTab onPick={openScorecard} />}
          {tab === 'portfolio' && <PortfolioTab onPick={openScorecard} />}
        </ErrorBoundary>
      </main>
      <footer>
        {/* "not *certified* financial advice" conceded that it is financial
            advice and merely uncertified, while the scorecard's own caveat
            (backend/scoring.py) denies the category outright. Two claims, one
            of them weaker, both on screen together on the Scorecard tab. This
            one now matches that one. */}
        Data: yfinance (OpenBB adapter ready) · AI: local Ollama · Decision support only,
        not financial advice.
      </footer>
    </div>
  );
}
