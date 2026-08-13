import { useState, useRef, useEffect } from 'react';
import { stream } from '../api';

export default function ChatBox({ ticker, aiOnline }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    const next = [...messages, { role: 'user', content: text }];
    setMessages(next);
    setInput('');
    setBusy(true);
    // Append an empty assistant turn and grow it as deltas arrive, so a 60-180s
    // CPU reply reads as typing instead of a frozen window.
    setMessages([...next, { role: 'assistant', content: '' }]);
    const replace = (content) => setMessages([...next, { role: 'assistant', content }]);
    try {
      let acc = '';
      await stream('/ai/chat', { messages: next, ticker: ticker || null }, (e) => {
        if (e.error) replace(`⚠ ${e.message}`);
        else {
          acc += e.delta;
          replace(acc);
        }
      });
    } catch (e) {
      replace(`⚠ ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel chat-panel">
      <div className="panel-title">
        Financial Expert Chat
        <span className={`ai-dot ${aiOnline ? 'on' : 'off'}`} title={aiOnline ? 'Local AI online' : 'Local AI offline'} />
      </div>
      {!aiOnline && (
        <div className="ai-offline-note">
          Local AI is offline. Install and start Ollama (see README). The chat will
          activate automatically.
        </div>
      )}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-hint">
            Ask about {ticker || 'a stock'}, e.g. “Is the current P/E justified?” or
            “Which valuation model fits this company?”
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            {m.content || (busy && i === messages.length - 1 ? 'Thinking…' : '')}
            {busy && i === messages.length - 1 && m.content && <span className="debate-cursor" />}
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <div className="chat-input-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="Ask your financial expert…"
          disabled={busy}
        />
        <button onClick={send} disabled={busy || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
