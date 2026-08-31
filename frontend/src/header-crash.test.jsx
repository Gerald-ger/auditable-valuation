/** @vitest-environment jsdom */
/**
 * A throw in the header must not take the whole app with it.
 *
 * `ErrorBoundary` wraps only the tab body (App.jsx), so everything above it —
 * the title, the search box and the tab nav — rendered unprotected. A render
 * throw in React unmounts the entire tree, which is the exact failure that
 * boundary was written to stop, happening in the ~20% of the tree it does not
 * cover. The nav is what makes it expensive: lose the header and the reader
 * cannot even switch to a tab that still works.
 *
 * Why the search box specifically, and not the whole header: `<h1>` is a string
 * literal and `<nav>` maps a module constant, so neither can throw on data.
 * `SearchBar` is the only part of the header that renders a fetched payload and
 * reads `localStorage`. Wrapping the whole header would also be worse — a
 * search-box throw would take the nav down with it, which is the outcome this
 * is trying to prevent.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import App from './App';
import { render, flush } from './test-utils';

const { api } = vi.hoisted(() => ({
  api: { get: vi.fn(), post: vi.fn(), del: vi.fn(), stream: vi.fn() },
}));
vi.mock('./api', () => api);

vi.mock('./components/TrackerTab', () => ({ default: () => <div id="t" /> }));
vi.mock('./components/ModelsTab', () => ({ default: () => <div id="m" /> }));
vi.mock('./components/ScorecardTab', () => ({ default: () => <div id="s" /> }));
vi.mock('./components/ScreenerTab', () => ({ default: () => <div id="scr" /> }));
vi.mock('./components/PortfolioTab', () => ({ default: () => <div id="p" /> }));
vi.mock('./components/SettingsTab', () => ({ default: () => <div id="set" /> }));

// The shape a real one would take: a response field the component indexed into
// before checking it existed.
vi.mock('./components/SearchBar', () => ({
  default: () => {
    throw new TypeError("Cannot read properties of undefined (reading 'symbol')");
  },
}));

const HEALTH = { status: 'ok', ai: { online: false }, source_changed_since_start: false };

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((path) =>
    Promise.resolve(path.includes('/health') ? HEALTH : { tickers: [] }));
});

describe('a header component that throws', () => {
  it('costs the search box and leaves the rest of the app standing', async () => {
    const { container } = render(<App />);
    await flush();

    // the tab nav is the thing worth saving: it is the way out
    const labels = [...container.querySelectorAll('nav button')].map((b) => b.textContent);
    expect(labels.length).toBeGreaterThan(0);
    expect(container.querySelector('h1')).not.toBeNull();
    // and the tab body still rendered
    expect(container.querySelector('#t')).not.toBeNull();
  });

  it('says so where the search box was, rather than failing silently', async () => {
    const { container } = render(<App />);
    await flush();
    expect(container.textContent).toContain('Search unavailable');
  });
});
