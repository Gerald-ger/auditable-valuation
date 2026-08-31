/** @vitest-environment jsdom */
/**
 * Google Translate rewrites the DOM underneath React, and React does not
 * survive it. Reported 2026-08-31 from a running browser: switching tabs with
 * the page translated threw
 *
 *   NotFoundError: Failed to execute 'insertBefore' on 'Node': The node before
 *   which the new node is to be inserted is not a child of this node.
 *
 * at `commitPlacement` -> `insertOrAppendPlacementNode`, with `main` and
 * `TrackerTab` in the component stack. The ErrorBoundary caught it and replaced
 * the whole tab with "This panel failed to render", whose suggested cause — a
 * stale backend — is the wrong one for this crash.
 *
 * These tests exist before any fix, to establish that the mechanism is
 * understood well enough to reproduce it. A fix that does not turn the first
 * test green is a fix for something else.
 */
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import { render } from './test-utils';

/**
 * Google Translate's rewrite, reduced to the single operation that breaks
 * React: each Text node is **replaced** by a `<font>` element carrying the same
 * words. The Text node leaves the document; React's fiber goes on pointing at
 * it, and uses it as the reference node the next time it inserts a sibling.
 *
 * This is what the real extension does — the `<font>` wrapper is visible in the
 * DOM of any translated page — reduced to one level and without the translation
 * itself, which is irrelevant to the failure.
 */
function translatePage(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    // The real extension honours `translate="no"` and `class="notranslate"`,
    // and skipping them here is what makes this a measuring instrument rather
    // than a demonstration: a fix that marks a subtree has to be able to show
    // up as a difference.
    acceptNode: (node) =>
      node.parentElement?.closest('[translate="no"], .notranslate')
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  });
  const texts = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) texts.push(n);
  for (const t of texts) {
    const font = document.createElement('font');
    font.textContent = t.nodeValue;
    t.parentNode.replaceChild(font, t);
  }
  return texts.length;
}

/**
 * Rerender and hand back the *root* error name, or null if it survived.
 *
 * The unwrapping is not incidental. React 19's `act` sometimes reports a
 * failed commit as an `AggregateError` carrying the real DOMException in
 * `.errors`, and sometimes throws the DOMException itself. A first draft of
 * this file asserted `e.name === 'NotFoundError'` directly and read the
 * resulting failure as "this shape does not crash" — the opposite of the truth,
 * and it very nearly sent a fix at the wrong file.
 */
function crashOnRerender(rerender, element) {
  try {
    rerender(element);
    return null;
  } catch (e) {
    const root = e.name === 'AggregateError' && e.errors?.length ? e.errors[0] : e;
    return root.name;
  }
}

/**
 * `App`'s shape at the point it breaks, and nothing else: one parent holding
 * several `{tab === '...' && <Component/>}` slots with text among them. The
 * real file has six such slots inside an ErrorBoundary inside `<main>`, plus
 * the footer line visible in the report's screenshot.
 */
function Tabs({ tab }) {
  return (
    <main>
      {tab === 'tracker' && <div className="tracker">Tracker</div>}
      Data: yfinance · Decision support only.
      {tab === 'models' && <div className="models">Models</div>}
    </main>
  );
}

describe('a translated page', () => {
  it('reproduces the crash: React inserts before a text node Translate removed', () => {
    const { container, rerender } = render(<Tabs tab="models" />);
    expect(translatePage(container)).toBeGreaterThan(0);

    // Switching to the tracker tab makes React insert that slot's node *before*
    // the footer text — the node Translate has just replaced.
    //
    // Asserted on the DOMException's *name*, not its message. jsdom words this
    // "The child can not be found in the parent."; Chrome words it "Failed to
    // execute 'insertBefore' on 'Node': The node before which the new node is
    // to be inserted is not a child of this node." Same defect, same name,
    // different sentence — so matching the sentence would pin the test to one
    // engine and would not have matched the report this was written from.
    const thrown = crashOnRerender(rerender, <Tabs tab="tracker" />);
    expect(thrown, 'the crash did not reproduce').not.toBeNull();
    expect(thrown).toBe('NotFoundError');
  });

  it('does not crash when the page was left alone, so the trigger is Translate', () => {
    const { rerender } = render(<Tabs tab="models" />);
    expect(() => rerender(<Tabs tab="tracker" />)).not.toThrow();
  });
});

// ── the two candidate fixes, measured rather than argued ─────────────
//
// Neither is applied to the application yet. These say what each one would buy,
// so the choice between "stop translation" and "keep translation" is made on
// evidence.

/** Candidate A: the subtree opts out of translation entirely. */
function TabsOptedOut({ tab }) {
  return (
    <main translate="no">
      {tab === 'tracker' && <div className="tracker">Tracker</div>}
      Data: yfinance · Decision support only.
      {tab === 'models' && <div className="models">Models</div>}
    </main>
  );
}

/** Candidate B: translation stays on; the bare text gets an element of its own. */
function TabsWrapped({ tab }) {
  return (
    <main>
      {tab === 'tracker' && <div className="tracker">Tracker</div>}
      <span>Data: yfinance · Decision support only.</span>
      {tab === 'models' && <div className="models">Models</div>}
    </main>
  );
}

describe('what each candidate fix buys', () => {
  it('A — translate="no" survives, because Translate never touches the subtree', () => {
    const { container, rerender } = render(<TabsOptedOut tab="models" />);
    expect(translatePage(container), 'nothing should have been rewritten').toBe(0);
    expect(crashOnRerender(rerender, <TabsOptedOut tab="tracker" />)).toBeNull();
  });

  it('B — a <span> survives too, and the page still translates', () => {
    const { container, rerender } = render(<TabsWrapped tab="models" />);
    // The text *is* rewritten — this fix does not opt out of anything.
    expect(translatePage(container), 'the page should still translate').toBeGreaterThan(0);
    // React's reference node is now the <span>, an element Translate leaves in
    // place, so the insert lands.
    expect(crashOnRerender(rerender, <TabsWrapped tab="tracker" />)).toBeNull();
  });
});

// ── how wide the problem is, which is the part that decides the fix ──
//
// Two real shapes from this codebase, both measured: `PriceChart`'s hover
// readout and `TrackerTab`'s chart caption. **Both crash.** So does the tab
// switcher above. The common factor is not any one component — it is a run of
// bare text sharing a parent with anything React later places, which is an
// ordinary way to write JSX and appears all over this app.
//
// That is the finding. Fixing the caption, or the readout, or the chart, would
// each stop one reproduction and leave the rest, and there is no way to tell
// from a diff whether a newly written line reintroduces it.

/** The readout, as written. Kept as a recorded negative result. */
function Legend({ bar }) {
  return (
    <div className="chart-legend">
      {bar.date}
      {bar.open !== undefined ? (
        <>
          {' '}O {bar.open?.toFixed(2)} C {bar.close?.toFixed(2)}
        </>
      ) : (
        <> {bar.value?.toFixed(2)}</>
      )}
      {' '}V {bar.volume}
    </div>
  );
}

const OHLC = { date: '2026-08-31', open: 1, close: 2, volume: 3 };
const LINE = { date: '2026-08-31', value: 9, volume: 3 };

/** `TrackerTab`'s chart caption as it was written until 2026-08-31. */
function CaptionBare({ warmup }) {
  return (
    <div className="chart-note">
      {(250).toLocaleString()} bars at 1d
      {warmup > 0 ? ` (+${warmup} before it)` : ''} · times in HKT
      {' '}· scroll to pan · drag to pan
    </div>
  );
}

/** The same caption with each conditional run owning an element. */
function CaptionWrapped({ warmup }) {
  return (
    <div className="chart-note" translate="no">
      <span>{(250).toLocaleString()} bars at 1d</span>
      {warmup > 0 ? <span> (+{warmup} before it)</span> : null}
      <span> · times in HKT · scroll to pan · drag to pan</span>
    </div>
  );
}

describe('every ordinary shape in this codebase', () => {
  it('the hover readout crashes — the first suspect, and it was one of several', () => {
    const { container, rerender } = render(<Legend bar={OHLC} />);
    translatePage(container);
    expect(crashOnRerender(rerender, <Legend bar={LINE} />)).toBe('NotFoundError');
  });
});

describe('the chart caption', () => {
  it('a conditional string turning non-empty is a placement, and it crashes', () => {
    const { container, rerender } = render(<CaptionBare warmup={0} />);
    translatePage(container);
    const crash = crashOnRerender(rerender, <CaptionBare warmup={50} />);
    expect(crash, 'the caption shape stopped reproducing the report').toBe('NotFoundError');
  });

  it('the same caption survives once each run owns an element', () => {
    const { container, rerender } = render(<CaptionWrapped warmup={0} />);
    translatePage(container);
    expect(crashOnRerender(rerender, <CaptionWrapped warmup={50} />)).toBeNull();
  });
});

// ── the fix, guarded where it lives ──────────────────────────────────

describe('the shipped document', () => {
  it('carries translate="no" on <html>, which is what actually fixes this', () => {
    /**
     * The tests above prove the mechanism and that the attribute neutralises
     * it. This one proves the attribute is still there — the fix lives in
     * `index.html`, which no component test renders, so without this it could
     * be dropped in a tidy-up and every test here would go on passing while
     * the application crashed for anyone with Translate on.
     */
    // `import.meta.url` is not a file: URL under Vite's transform, so the path
    // is resolved from the working directory instead — which is `frontend/`
    // when vitest runs, and the repository root if it is ever run from there.
    const path = ['index.html', 'frontend/index.html'].map((p) => resolve(p)).find(existsSync);
    expect(path, 'index.html was not found from the working directory').toBeDefined();
    expect(readFileSync(path, 'utf-8')).toMatch(/<html[^>]*\stranslate="no"/);
  });
});
