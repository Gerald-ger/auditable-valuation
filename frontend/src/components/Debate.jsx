import { useState } from 'react';
import { stream } from '../api';

/**
 * Bull → bear → verdict, streamed as three separate passes.
 *
 * One model asked for "bull/base/bear" at once averages the views into mush.
 * Running the sides separately, each seeing the previous argument, keeps the
 * disagreement visible — which is the part that carries information.
 */
const STAGES = [
  { key: 'bull', label: 'Bull case', cls: 'up' },
  { key: 'bear', label: 'Bear case', cls: 'down' },
  { key: 'verdict', label: 'Verdict, and what would change it', cls: 'gold' },
];

export default function Debate({ ticker, aiOnline }) {
  const [text, setText] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [active, setActive] = useState(null);

  async function run() {
    setBusy(true);
    setError(null);
    setText({});
    setActive('bull');
    try {
      await stream(`/ai/debate/${ticker}`, {}, (e) => {
        if (e.error) {
          setError(e.message);
          return;
        }
        setActive(e.stage);
        setText((prev) => ({ ...prev, [e.stage]: (prev[e.stage] ?? '') + e.delta }));
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      setActive(null);
    }
  }

  return (
    <div className="panel">
      <div className="panel-title">
        Bull vs bear debate
        <button className="primary" onClick={run} disabled={busy || !aiOnline}>
          {busy ? 'Debating…' : aiOnline ? 'Run debate' : 'AI offline'}
        </button>
      </div>

      {!aiOnline && (
        <div className="ai-offline-note">
          Requires the local AI. Install Ollama to enable (see README). Three passes on a
          CPU-only 7B model takes several minutes; the text streams in as it is written.
        </div>
      )}
      {error && <div className="error-banner">{error}</div>}

      {STAGES.map(({ key, label, cls }) =>
        text[key] !== undefined ? (
          <div key={key} className="debate-stage">
            <div className={`debate-label ${cls}`}>
              {label}
              {active === key && <span className="debate-cursor" />}
            </div>
            <div className="outlook-text">{text[key]}</div>
          </div>
        ) : null,
      )}

      {busy && !text.bull && <div className="chart-note">Building the bull case…</div>}
    </div>
  );
}
