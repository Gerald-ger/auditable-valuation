import { useEffect, useState } from 'react';
import { get, post, del } from '../api';

/**
 * The one credential this platform reads, and the only place it can be typed.
 *
 * Before this it meant hand-creating `~/.openbb_platform/user_settings.json`
 * with an exact JSON shape, at a path most people have never opened — and six
 * ways of getting that wrong all produced the same silence, because the FMP
 * tier in `comps.py` catches everything and falls through to the keyless one.
 *
 * Saving writes that same file (read-modify-write: whatever else is in it is
 * read back and written out untouched) and then makes **one real call** so this
 * screen can say "working" or "rejected" while the person who typed it is still
 * looking. That verification is the point; the text box is the easy half.
 *
 * There is no endpoint that returns the key, so this component cannot show one
 * back — only whether one is set. Nothing here is authenticated.
 */
export default function SettingsTab() {
  const [status, setStatus] = useState(null);
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    get('/health')
      .then((s) => setStatus(s.fmp ?? { configured: false, last_call: null }))
      .catch(() => setError('Could not reach the backend.'));
  }, []);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      setStatus(await post('/settings/fmp-key', { key }));
      setKey('');   // not kept in component state a moment longer than needed
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError('');
    try {
      setStatus(await del('/settings/fmp-key'));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!status && !error) return <div className="empty-state loading">Checking…</div>;

  // Four states, and the difference between the last two is the whole feature:
  // a key that is set is not the same as a key that works.
  const verdict = !status?.configured
    ? ['No key set.',
       'Peer discovery falls back to a curated list of 23 tickers and a keyless '
       + 'screener below it. That works — comps for anything outside the curated '
       + 'list are just thinner than they would be with a key.']
    : status.last_call === 'failed'
      ? ['A key is set, and its last call to FMP failed.',
         'Usually the key is wrong or the free tier’s daily quota is spent. Peer '
         + 'discovery has fallen back to the keyless tier in the meantime.']
      : status.last_call === 'ok'
        ? ['A key is set and working.',
           'The last call to FMP succeeded.']
        : ['A key is set.',
           'It has not been used yet, so there is nothing to report about it. '
           + 'Saving it again would check.'];

  return (
    <div className="settings-tab">
      <div className="panel">
        <div className="panel-title">Financial Modeling Prep API key</div>

        <p className={status?.last_call === 'failed' ? 'fmp-verdict bad' : 'fmp-verdict'}>
          <b>{verdict[0]}</b> {verdict[1]}
        </p>

        <form className="position-form" onSubmit={save}>
          <label className="grow">
            <span>Key</span>
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={status?.configured ? 'Replace the stored key' : 'Paste your key'}
              autoComplete="off"
              spellCheck="false"
            />
          </label>
          <button className="primary" type="submit" disabled={busy || !key.trim()}>
            {busy ? 'Checking…' : 'Save and verify'}
          </button>
          {status?.configured && (
            <button type="button" onClick={remove} disabled={busy}>Remove</button>
          )}
        </form>

        {error && <div className="error-banner">{error}</div>}
      </div>

      <div className="notice-banner">
        <b>Where this goes.</b> Into{' '}
        <code>~/.openbb_platform/user_settings.json</code> on this machine — the file
        OpenBB already reads, outside the repository and never committed. Only the
        one <code>fmp_api_key</code> field is changed; anything else in that file,
        including other providers’ credentials, is read back and written out
        untouched. The key is not sent anywhere except to FMP itself, and no
        endpoint here will hand it back — <code>/api/health</code> reports only
        whether one is set.
        <br /><br />
        <b>Skipping this is fine.</b> A free key at{' '}
        <code>site.financialmodelingprep.com</code> buys automatic peer discovery
        across FMP’s coverage instead of the built-in list of 23. Everything else —
        the DCF, the scorecard, the statements — needs no credential at all.
      </div>
    </div>
  );
}
