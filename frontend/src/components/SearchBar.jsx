import { useEffect, useRef, useState } from 'react';
import { get } from '../api';
import { readRecents, pushRecent } from '../recents';

/**
 * Typo-tolerant ticker search with a clickable result list.
 *
 * Why it exists: the header used to be a bare text box that sent whatever you
 * typed straight to yfinance, so one wrong character produced an empty chart
 * and no explanation. Selecting from a list of real symbols makes an
 * unresolvable ticker impossible to submit by accident.
 *
 * Recents live in localStorage (see ../recents.js), so they are a property of
 * this browser rather than of the portfolio.
 */
const DEBOUNCE_MS = 220;

export default function SearchBar({ value, onSelect, saved = [] }) {
  const [query, setQuery] = useState(value ?? '');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(0);
  const [recents, setRecents] = useState(readRecents);
  const boxRef = useRef(null);
  // Results can arrive out of order — a slow lookup for "app" must not
  // overwrite the newer one for "apple". Only the latest request may render.
  const requestRef = useRef(0);

  useEffect(() => setQuery(value ?? ''), [value]);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      return undefined;
    }
    const id = setTimeout(() => {
      const seq = ++requestRef.current;
      setBusy(true);
      get(`/search?q=${encodeURIComponent(q)}`)
        .then((r) => {
          if (seq === requestRef.current) setResults(r.results ?? []);
        })
        .catch(() => {
          if (seq === requestRef.current) setResults([]);
        })
        .finally(() => {
          if (seq === requestRef.current) setBusy(false);
        });
    }, DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [query]);

  useEffect(() => {
    const onDocClick = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  function choose(symbol) {
    setRecents(pushRecent(symbol));
    setQuery(symbol);
    setOpen(false);
    setResults([]);
    onSelect(symbol);
  }

  function onKeyDown(e) {
    if (!open || !results.length) {
      // Enter with no list still submits, so a known ticker needs no mouse
      if (e.key === 'Enter' && query.trim()) choose(query.trim().toUpperCase());
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => (i + 1) % results.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(results[Math.min(active, results.length - 1)].symbol);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  }

  const chips = [
    ...saved.map((t) => ({ ticker: t, kind: 'saved' })),
    ...recents.filter((t) => !saved.includes(t)).map((t) => ({ ticker: t, kind: 'recent' })),
  ].slice(0, 12);

  return (
    <div className="search-box" ref={boxRef}>
      <div className="search-field">
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search ticker or company — AAPL, Tencent, 0700.HK"
          aria-label="Search for a stock by ticker or company name"
          autoComplete="off"
        />
        {busy && <span className="search-spinner" aria-hidden="true" />}
      </div>

      {open && query.trim() !== '' && (
        <div className="search-results">
          {results.length === 0 ? (
            <div className="search-empty">
              {busy ? 'Searching…' : `No listing matches “${query.trim()}”.`}
            </div>
          ) : (
            results.map((r, i) => (
              <button
                key={`${r.symbol}-${r.source}`}
                className={`search-row ${i === active ? 'active' : ''}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(r.symbol)}
              >
                <span className="search-symbol">{r.symbol}</span>
                <span className="search-name">{r.name}</span>
                {r.exchange && <span className="search-exch">{r.exchange}</span>}
              </button>
            ))
          )}
        </div>
      )}

      {chips.length > 0 && (
        <div className="search-chips">
          {chips.map(({ ticker, kind }) => (
            <button
              key={ticker}
              className={`search-chip ${kind}`}
              title={kind === 'saved' ? 'In your portfolio or watchlist' : 'Recently viewed'}
              onClick={() => choose(ticker)}
            >
              {ticker}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
