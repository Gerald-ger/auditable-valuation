/**
 * @vitest-environment jsdom
 *
 * One decision in this component, and it is not visible in what it renders: when
 * a reload starts, does the chart stay mounted?
 *
 * It has to. `PriceChart`'s root is the element passed to `requestFullscreen`,
 * and the Fullscreen API ends full screen when its element leaves the document.
 * Swapping the chart for a "Loading…" placeholder does exactly that, so before
 * 2026-08-20 choosing a period full screen threw you back to the page —
 * measured in Chrome: one click and `.chart-panel` was gone from the DOM.
 *
 * `PriceChart` is stubbed with a mount counter rather than rendered. The real one
 * needs `lightweight-charts`, which cannot run under jsdom (see the docblock in
 * PriceChart.test.jsx), and a stub is what makes "was it unmounted?" answerable
 * at all — the question is about TrackerTab's rendering decision, not the chart.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import TrackerTab from './TrackerTab';
import { render, click, flush } from '../test-utils';

const { api, chart } = vi.hoisted(() => ({
  api: { get: vi.fn(), stream: vi.fn() },
  chart: { mounts: 0, unmounts: 0, props: null },
}));

vi.mock('../api', () => api);
// Its own component with its own fetches, and nothing here is about chat.
vi.mock('./ChatBox', () => ({ default: () => null }));
vi.mock('./PriceChart', async () => {
  const { useEffect } = await import('react');
  // Named, and capitalised, because it really is a component: the linter's
  // rules-of-hooks check keys off the name to decide whether `useEffect` is
  // legal here, and an arrow assigned straight to `default` has none.
  const PriceChartStub = (props) => {
    chart.props = props;
    useEffect(() => {
      chart.mounts += 1;
      return () => { chart.unmounts += 1; };
    }, []);
    return <div className="chart-panel" />;
  };
  return { default: PriceChartStub };
});

const BARS = Array.from({ length: 5 }, (_, i) => ({
  time: `2026-01-0${i + 1}`, open: 1, high: 2, low: 0, close: 1, volume: 10,
}));

/** Every endpoint the tab reaches for, with `/history` under the caller's control. */
function serve({ history = { bars: BARS, interval: '1d', warmup_bars: 0 } } = {}) {
  api.get.mockImplementation((url) => {
    if (url.includes('/quote')) {
      return Promise.resolve({ ticker: 'AAPL', name: 'Apple', exchange: 'NasdaqGS',
        price: 100, previous_close: 99, currency: 'USD' });
    }
    if (url.includes('/history')) return Promise.resolve(history);
    if (url.includes('/events')) return Promise.resolve({ events: [], filings_supported: true });
    return Promise.resolve({});
  });
}

const periodButton = (container, label) =>
  [...container.querySelectorAll('.period-picker button')].find((b) => b.textContent === label);

beforeEach(() => {
  vi.clearAllMocks();
  chart.mounts = 0;
  chart.unmounts = 0;
  chart.props = null;
});

describe('the first load', () => {
  it('shows a placeholder while there is nothing to draw yet', async () => {
    serve();
    const { container, unmount } = render(<TrackerTab ticker="AAPL" aiOnline={false} />);
    // No full screen is possible with no chart, so the placeholder costs nothing
    // here and is better than an empty pane.
    expect(container.querySelector('.empty-state.loading')).not.toBeNull();
    expect(container.querySelector('.chart-panel')).toBeNull();

    await flush();
    expect(container.querySelector('.chart-panel')).not.toBeNull();
    unmount();
  });
});

describe('reloading with a chart already on screen', () => {
  it('keeps the chart mounted, because unmounting it would end full screen', async () => {
    serve();
    const { container, unmount } = render(<TrackerTab ticker="AAPL" aiOnline={false} />);
    await flush();
    /**
     * Counted across the click rather than from zero. The very first load
     * already builds the chart, drops it and builds it again — `loading` starts
     * false, so the opening render draws an empty chart before the effect marks
     * it busy. That is unchanged from before this test existed and is not what
     * is being asserted; what matters is that a *reload* moves neither counter.
     */
    const built = chart.mounts;
    const torn = chart.unmounts;

    // never resolves: hold the component in the state a real fetch passes through
    api.get.mockReturnValue(new Promise(() => {}));
    click(periodButton(container, '5d'));

    expect(chart.unmounts).toBe(torn); // not taken out of the document
    expect(chart.mounts).toBe(built); // and not rebuilt behind a placeholder
    expect(container.querySelector('.chart-panel')).not.toBeNull();
    expect(container.querySelector('.empty-state.loading')).toBeNull();
    unmount();
  });

  it('tells the chart it is busy, so it can say so itself', async () => {
    serve();
    const { container, unmount } = render(<TrackerTab ticker="AAPL" aiOnline={false} />);
    await flush();
    expect(chart.props.loading).toBe(false);

    api.get.mockReturnValue(new Promise(() => {}));
    click(periodButton(container, '5d'));
    expect(chart.props.loading).toBe(true);
    unmount();
  });
});

describe('what the chart is given', () => {
  it('hands down everything the full-screen bar needs to change chart', async () => {
    // Full screen, the page's own picker and search box are unreachable — the
    // panel is the fullscreen element and nothing outside it renders. These
    // props are how the chart offers them instead.
    const onTicker = vi.fn();
    serve();
    const { unmount } = render(
      <TrackerTab ticker="AAPL" aiOnline={false} saved={['MSFT']} onTicker={onTicker} />);
    await flush();

    expect(chart.props.periods).toEqual(['1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', 'max']);
    expect(chart.props.period).toBe('1y');
    expect(typeof chart.props.onPeriod).toBe('function');
    expect(chart.props.saved).toEqual(['MSFT']);
    expect(chart.props.onTicker).toBe(onTicker);
    unmount();
  });

  it('passes the period the chart reported back, so the two cannot disagree', async () => {
    serve();
    const { container, unmount } = render(<TrackerTab ticker="AAPL" aiOnline={false} />);
    await flush();

    click(periodButton(container, '5d'));
    expect(chart.props.period).toBe('5d');
    await flush();
    expect(api.get).toHaveBeenCalledWith('/stock/AAPL/history?period=5d');
    unmount();
  });
});
