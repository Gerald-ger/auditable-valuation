import { useEffect, useRef, useState } from 'react';
import { get } from './api';
import TrackerTab from './components/TrackerTab';
import ModelsTab from './components/ModelsTab';
import ScorecardTab from './components/ScorecardTab';
import ScreenerTab from './components/ScreenerTab';
import PortfolioTab from './components/PortfolioTab';
import SearchBar from './components/SearchBar';
import ErrorBoundary from './components/ErrorBoundary';
import SettingsTab from './components/SettingsTab';
import { pushRecent } from './recents';

const TABS = [
  ['tracker', '📈 Tracker'],
  ['models', '🧮 Financial Models'],
  ['scorecard', '🎯 Scorecard'],
  ['screener', '📊 Screener'],
  ['portfolio', '💼 Portfolio'],
  ['settings', '🔑 API Key'],
];

// Screener and Portfolio work across many tickers, so the single-ticker box in
// the header does not apply to them.
const TICKER_TABS = new Set(['tracker', 'models', 'scorecard']);

// Shown in place of Tracker and Screener under demo mode. Tracker needs daily
// OHLCV, news and filings; Screener needs a peer group. The capture carries
// weekly closes only, and the eight companies are eight *sectors* — chosen to
// exercise edge cases, not to compare with one another.
function DemoTabNotice() {
  return (
    <div className="notice-banner">
      <b>Not available in demo mode.</b> This tab needs data the capture does not
      carry: daily open/high/low/volume bars, news, SEC filings and a peer group.
      Rather than draw a chart with holes in it, demo mode withholds the tab —
      a stripped chart reads as a broken one. Open <b>Scorecard</b> or{' '}
      <b>Financial Models</b> above, which the capture answers in full.
    </div>
  );
}

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
  // Serving the committed fixtures instead of a live vendor. Read off the same
  // `/health` poll as the two flags above.
  const [demo, setDemo] = useState(false);
  // An FMP key that is present and not working. Deliberately not raised when no
  // key is configured: that is the documented default, it works, and the keyless
  // tier below it covers the gap — so saying anything there would be noise on a
  // screen that is behaving correctly. The pair is what makes this reportable.
  const [fmpFailing, setFmpFailing] = useState(false);
  // Demo mode lands on the Scorecard rather than the default Tracker, since the
  // Tracker is one of the two tabs it cannot answer — a demo whose first screen
  // is a notice explaining what it cannot do has wasted the only 30 seconds it
  // gets. Once, via a ref: repeating it on the 30 s poll would bounce a visitor
  // who deliberately opened the Tracker back out of it.
  const demoLanded = useRef(false);
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
          setDemo(s.demo === true);
          setFmpFailing(s.fmp?.configured === true && s.fmp?.last_call === 'failed');
          if (s.demo === true && !demoLanded.current) {
            demoLanded.current = true;
            setTab((t) => (t === 'tracker' ? 'scorecard' : t));
          }
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
        {fmpFailing && (
          <div className="ai-offline-note">
            <b>Your FMP key is configured, but its last call failed.</b> Peer
            discovery has fallen back to the keyless tier, so comps for anything
            outside the curated list are thinner than they should be. Usually the
            key is wrong or the free tier&rsquo;s daily quota is spent — see{' '}
            <b>Credentials</b> in the README. Everything else is unaffected.
          </div>
        )}
        {backendStale && (
          <div className="ai-offline-note">
            <b>The backend is running older code than this project folder.</b> Python
            files changed after the server started, so new fields are missing from
            its responses and any panel that reads one will simply not appear.
            Restart it — <code>-m uvicorn backend.main:app --port 8000</code>
            {' '}— then reload this page.
          </div>
        )}
        {demo && (
          <div className="notice-banner">
            <b>Demo mode — real data, frozen.</b> Eight companies&rsquo; financial
            statements and prices exactly as captured between <b>2026-08-10</b>{' '}
            and <b>2026-08-19</b> (see{' '}
            <code>backend/tests/fixtures/PROVENANCE.md</code>). Nothing here is
            fabricated and nothing is live, so every number is reproducible — these
            are the same bytes the test suite pins its golden scores to. No API key
            and no network are used. <b>Scorecard</b> and <b>Financial Models</b>{' '}
            answer in full; <b>Tracker</b> and <b>Screener</b> do not. Anything you
            save in <b>Portfolio</b> is written to a separate demo database and never
            reaches your own.
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
          {tab === 'tracker' && (demo ? (
            <DemoTabNotice />
          ) : (
            <TrackerTab
              ticker={ticker}
              aiOnline={aiOnline}
              saved={saved}
              onTicker={setTicker}
            />
          ))}
          {tab === 'models' && <ModelsTab key={ticker} ticker={ticker} />}
          {tab === 'scorecard' && <ScorecardTab key={ticker} ticker={ticker} aiOnline={aiOnline} />}
          {tab === 'screener' &&
            (demo ? <DemoTabNotice /> : <ScreenerTab onPick={openScorecard} />)}
          {tab === 'portfolio' && <PortfolioTab onPick={openScorecard} />}
          {/* Its own notice, not DemoTabNotice: that one explains missing OHLCV
              and news, which has nothing to do with why a key is pointless here.
              The backend refuses the write regardless — hiding a tab is not a
              control, and on a hosted demo the filesystem is not the visitor's. */}
          {tab === 'settings' && (demo ? (
            <div className="notice-banner">
              <b>Not available in demo mode.</b> Demo mode serves the committed
              fixtures and reaches no vendor at all, so an API key would change
              nothing — and if this is a hosted demo, the machine storing it would
              not be yours.
            </div>
          ) : <SettingsTab />)}
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
