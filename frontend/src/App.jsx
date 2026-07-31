import { useEffect, useState } from 'react';
import { get } from './api';
import TrackerTab from './components/TrackerTab';
import ModelsTab from './components/ModelsTab';
import ScorecardTab from './components/ScorecardTab';

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

  return (
    <div className="app">
      <header>
        <h1>Stock Analysis Platform</h1>
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
        <nav>
          <button className={tab === 'tracker' ? 'active' : ''} onClick={() => setTab('tracker')}>
            📈 Tracker
          </button>
          <button className={tab === 'models' ? 'active' : ''} onClick={() => setTab('models')}>
            🧮 Financial Models
          </button>
          <button className={tab === 'scorecard' ? 'active' : ''} onClick={() => setTab('scorecard')}>
            🎯 Scorecard
          </button>
        </nav>
      </header>
      <main>
        {tab === 'tracker' && <TrackerTab ticker={ticker} aiOnline={aiOnline} />}
        {tab === 'models' && <ModelsTab ticker={ticker} />}
        {tab === 'scorecard' && <ScorecardTab ticker={ticker} aiOnline={aiOnline} />}
      </main>
      <footer>
        Data: yfinance (OpenBB adapter ready) · AI: local Ollama · Decision support only —
        not certified financial advice.
      </footer>
    </div>
  );
}
