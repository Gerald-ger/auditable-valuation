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
 * Saving makes **one real call first**, and writes the file only if the key comes
 * back working. That order is the whole safety property, and it was the wrong way
 * round for the first few hours of this feature's life: on 2026-08-28 a
 * placeholder typed to see what the tab did overwrote a real key, the probe
 * correctly reported "failed", and the report arrived after the loss. A verdict
 * you cannot act on is not a safeguard.
 *
 * The write is still read-modify-write — everything else in that file is read
 * back and written out untouched — with the previous version kept as `.bak`.
 *
 * There is no endpoint that returns the key, so this component cannot show one
 * back — only whether one is set. Nothing here is authenticated.
 */
export default function SettingsTab() {
  const [status, setStatus] = useState(null);
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // A save that was refused. Distinct from `status.last_call === 'failed'`,
  // which is about the key that is *stored* — after a rejection those are two
  // different keys and conflating them is how the first version lost one.
  const [rejected, setRejected] = useState(false);

  useEffect(() => {
    get('/health')
      .then((s) => setStatus(s.fmp ?? { configured: false, last_call: null }))
      .catch(() => setError('Could not reach the backend.'));
  }, []);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    setRejected(false);
    try {
      const res = await post('/settings/fmp-key', { key });
      setStatus(res);
      if (res.saved) {
        setKey('');           // not kept a moment longer than needed
      } else {
        // Left in the box on purpose: a rejected key is usually a rejected
        // *paste*, and clearing it would make the reader start over rather
        // than look at what they typed.
        setRejected(true);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError('');
    setRejected(false);
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

        {rejected && (
          <div className="error-banner">
            <b>That key was rejected by FMP, so nothing was changed.</b> Whatever
            was stored before is still stored. Check for a stray space or a
            truncated paste — and if FMP itself is down or the free tier’s daily
            quota is spent, a perfectly good key is refused here too, so it is
            worth trying again later before assuming the key is wrong.
          </div>
        )}
        {error && <div className="error-banner">{error}</div>}
      </div>

      <div className="notice-banner">
        <b>Where this goes.</b> Into{' '}
        <code>~/.openbb_platform/user_settings.json</code> on this machine — the file
        OpenBB already reads, outside the repository and never committed. Only the
        one <code>fmp_api_key</code> field is changed; anything else in that file,
        including other providers’ credentials, is read back and written out
        untouched, and the previous version of the whole file is kept beside it as{' '}
        <code>user_settings.json.bak</code>. The key is not sent anywhere except to
        FMP itself, and no endpoint here will hand it back — <code>/api/health</code>{' '}
        reports only whether one is set.
        <br /><br />
        <b>Nothing is written until the key works.</b> Saving sends one real request
        to FMP first; only a key that comes back working is stored. A rejected one
        never reaches the file, so trying a key out cannot cost you the one you
        already have.
        <br /><br />
        <b>Skipping this is fine.</b> A free key at{' '}
        <code>site.financialmodelingprep.com</code> buys automatic peer discovery
        across FMP’s coverage instead of the built-in list of 23. Everything else —
        the DCF, the scorecard, the statements — needs no credential at all.
      </div>
    </div>
  );
}
