/** @vitest-environment jsdom */
/**
 * App's demo-mode gating.
 *
 * The failure this guards is the quiet one from the backend side, seen from the
 * front: if `/health` reports demo and the UI does not say so, a visitor reads
 * data captured in August 2026 as today's market. There is no error to notice —
 * the numbers are real, just frozen — so the banner is the only thing standing
 * between "a demo" and "a wrong quote".
 *
 * Both directions are asserted. A banner that appeared in normal mode would be
 * a worse bug than one that never appeared, because it would tell a live user
 * their live numbers are stale.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import App from './App';
import { render, click, flush } from './test-utils';

const { api } = vi.hoisted(() => ({
  api: { get: vi.fn(), post: vi.fn(), del: vi.fn(), stream: vi.fn() },
}));
vi.mock('./api', () => api);

// The five tabs are stubbed: this file is about which one App decides to show,
// and the real TrackerTab fetches three endpoints on mount (TrackerTab.jsx:36-40)
// which would make the test about TrackerTab instead.
vi.mock('./components/TrackerTab', () => ({ default: () => <div id="t" /> }));
vi.mock('./components/ModelsTab', () => ({ default: () => <div id="m" /> }));
vi.mock('./components/ScorecardTab', () => ({ default: () => <div id="s" /> }));
vi.mock('./components/ScreenerTab', () => ({ default: () => <div id="scr" /> }));
vi.mock('./components/PortfolioTab', () => ({ default: () => <div id="p" /> }));
vi.mock('./components/SearchBar', () => ({ default: () => <div id="search" /> }));

const HEALTH = { status: 'ok', ai: { online: false }, source_changed_since_start: false };

/**
 * Branch on URL, not one blanket resolve: App calls `/health` on mount and
 * `/portfolio/tickers` on every tab change, and handing the health payload to
 * the second would make `r.tickers` undefined.
 */
function serve({ demo = false, fmp = undefined } = {}) {
  api.get.mockImplementation((url) => {
    if (url.includes('/health')) return Promise.resolve({ ...HEALTH, demo, fmp });
    if (url.includes('/portfolio/tickers')) return Promise.resolve({ tickers: [] });
    return Promise.resolve({});
  });
}

async function mount() {
  const r = render(<App />);
  await flush();
  return r;
}

/** The nav button whose label contains `label`. */
function tabButton(container, label) {
  return [...container.querySelectorAll('nav button')]
    .find((b) => b.textContent.includes(label));
}

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = '';
});

describe('normal mode', () => {
  it('shows no demo banner and mounts the Tracker', async () => {
    serve({ demo: false });
    const { container } = await mount();

    expect(container.textContent).not.toContain('Demo mode');
    expect(container.querySelector('#t')).not.toBeNull();
  });

  it('leaves the Screener reachable', async () => {
    serve({ demo: false });
    const { container } = await mount();

    click(tabButton(container, 'Screener'));
    await flush();

    expect(container.querySelector('#scr')).not.toBeNull();
    expect(container.textContent).not.toContain('Not available in demo mode');
  });

  it('treats a missing `demo` key as normal mode', async () => {
    // An older backend does not send the field at all. `s.demo === true` is what
    // makes that read as live rather than as demo.
    api.get.mockImplementation((url) =>
      Promise.resolve(url.includes('/health') ? HEALTH : { tickers: [] }));
    const { container } = await mount();

    expect(container.textContent).not.toContain('Demo mode');
    expect(container.querySelector('#t')).not.toBeNull();
  });
});

describe('demo mode', () => {
  it('states that the data is real, frozen, and dated', async () => {
    serve({ demo: true });
    const { container } = await mount();

    const text = container.textContent;
    expect(text).toContain('Demo mode');
    // The three things a visitor would otherwise get wrong.
    expect(text).toContain('2026-08-10');
    expect(text).toMatch(/nothing is live/i);
    expect(text).toMatch(/Tracker/);
    // Portfolio stays enabled in demo mode, so the banner has to say where its
    // writes go. Before the store was isolated they went into the real database.
    expect(text).toMatch(/separate demo database/i);
  });

  it('lands on the Scorecard rather than the tab it cannot answer', async () => {
    serve({ demo: true });
    const { container } = await mount();

    expect(container.querySelector('#s')).not.toBeNull();
    expect(container.querySelector('#t')).toBeNull();
  });

  it('withholds Tracker and Screener behind a notice, and mounts neither', async () => {
    serve({ demo: true });
    const { container } = await mount();

    for (const [label, id] of [['Tracker', '#t'], ['Screener', '#scr']]) {
      click(tabButton(container, label));
      await flush();
      expect(container.textContent).toContain('Not available in demo mode');
      // Not merely hidden: the component must not mount, or its effect fires.
      expect(container.querySelector(id)).toBeNull();
    }
  });

  it('keeps Financial Models and Portfolio working', async () => {
    serve({ demo: true });
    const { container } = await mount();

    for (const [label, id] of [['Financial Models', '#m'], ['Portfolio', '#p']]) {
      click(tabButton(container, label));
      await flush();
      expect(container.querySelector(id)).not.toBeNull();
      expect(container.textContent).not.toContain('Not available in demo mode');
    }
  });

  it('does not bounce a visitor who deliberately opens the Tracker', async () => {
    // The landing redirect runs once, via a ref. On the 30 s `/health` poll it
    // must not fire again, or a demo visitor reading the notice would be thrown
    // back to the Scorecard mid-sentence.
    vi.useFakeTimers();
    try {
      serve({ demo: true });
      const { container } = await mount();

      click(tabButton(container, 'Tracker'));
      await flush();
      expect(container.textContent).toContain('Not available in demo mode');

      await vi.advanceTimersByTimeAsync(31000);
      await flush();

      expect(container.textContent).toContain('Not available in demo mode');
      expect(container.querySelector('#s')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

/**
 * The FMP key banner. It fires on a *pair* of conditions, and the reason the
 * pair matters is that either half alone is a normal, working state: no key
 * configured is the documented default, and a configured key that has not been
 * used yet has nothing to report. Only "present and failing" is news.
 */
describe('FMP key status', () => {
  const banner = (c) =>
    [...c.querySelectorAll('.ai-offline-note')]
      .find((d) => d.textContent.includes('FMP key'));

  it('warns when a configured key is failing', async () => {
    serve({ fmp: { configured: true, last_call: 'failed' } });
    const { container } = await mount();
    expect(banner(container)).toBeDefined();
    // Says what still works, so the reader knows the scope of the damage.
    expect(banner(container).textContent).toContain('keyless tier');
  });

  it('stays quiet when no key is configured, even though the call did fail', async () => {
    // Not a contrived pair — it is what every install without a key produces.
    // OpenBB raises for a missing credential, so `_fmp_peers` records "failed",
    // and dropping the `configured` half of the condition would tell everyone
    // who never set a key that the key they never set has stopped working.
    serve({ fmp: { configured: false, last_call: 'failed' } });
    expect(banner((await mount()).container)).toBeUndefined();
  });

  it('stays quiet before the key has been used', async () => {
    serve({ fmp: { configured: true, last_call: null } });
    expect(banner((await mount()).container)).toBeUndefined();
  });

  it('stays quiet while the key is working', async () => {
    serve({ fmp: { configured: true, last_call: 'ok' } });
    expect(banner((await mount()).container)).toBeUndefined();
  });

  it('survives a backend too old to send the field at all', async () => {
    // Not hypothetical here: a backend running older code than the folder is
    // this project's most repeated self-inflicted wound, and it is exactly the
    // condition under which a new response field is simply absent.
    serve({ fmp: undefined });
    const { container } = await mount();
    expect(banner(container)).toBeUndefined();
    expect(container.querySelector('nav')).not.toBeNull();
  });
});
