import { Component } from 'react';

/**
 * Stops one broken component from blanking the whole page.
 *
 * Why this exists: a render-time throw in React unmounts the entire tree, so
 * the app went completely black with no message. The trigger was a stale
 * backend — the frontend hot-reloaded to a build expecting
 * `/history` -> {bars, interval, bars_per_day} while the running server still
 * returned a bare array, so `bars` arrived undefined and `bars.length` threw
 * during render. A blank screen gives the reader nothing to act on, and the
 * actual cause (restart the backend) is not guessable from it.
 *
 * Must be a class: hooks cannot catch render errors.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    // `resetKey` is mirrored into state because that is the only way to compare
    // it against the previous render from a static method.
    this.state = { error: null, stack: null, resetKey: props.resetKey };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  /**
   * Clear a stale error when the caller moves to a different tab or ticker.
   *
   * This used to be a `key` on the element, which did the same job by throwing
   * the whole subtree away and building a new one. That is more than it needs
   * to do: it also destroyed the tracker's chart on every ticker change, and
   * since the chart panel *is* the fullscreen element, destroying it dropped
   * the browser out of full screen — so switching stock full screen was
   * impossible by construction. Resetting here leaves a healthy subtree alone.
   *
   * Nothing is lost in the error case: React has already unmounted the children
   * that threw, so clearing the flag mounts them fresh either way.
   *
   * Derived here rather than set from `componentDidUpdate`, which was the first
   * version: that clears the error one render *after* the key changed, so the
   * new ticker gets a frame of the old ticker's error panel before recovering.
   * This is also the pattern React documents for resetting state on a prop
   * change, and the one the linter does not warn about.
   */
  static getDerivedStateFromProps(props, state) {
    if (props.resetKey === state.resetKey) return null;
    return { error: null, stack: null, resetKey: props.resetKey };
  }

  componentDidCatch(error, info) {
    // keep the stack in the console for the dev who is about to go looking
    console.error('Render failed:', error, info?.componentStack);
    // ...and on screen, because the console is not where a reader looks. A
    // message alone names the property that was null and not the line that read
    // it, which on `Cannot read properties of null (reading 'id')` left an
    // intermittent drag crash with several candidate call sites and no way to
    // choose between them. Hidden behind a disclosure so the panel still leads
    // with the actionable sentence.
    this.setState({ stack: [error?.stack, info?.componentStack].filter(Boolean).join('\n\n') });
  }

  render() {
    const { error, stack } = this.state;
    if (!error) return this.props.children;
    // The panel below is sized for a tab body. A boundary guarding something
    // inline — the header's search box — needs to fail in the space it occupies
    // rather than push the nav down the page, so callers there pass their own.
    if (this.props.fallback) return this.props.fallback;
    return (
      <div className="error-boundary">
        <div className="error-boundary-title">This panel failed to render.</div>
        <p>
          The most common cause is a <strong>stale backend</strong>: if the API is still
          running an older build than the page, a response can arrive in a shape the UI
          does not expect. Restart the backend, then reload.
        </p>
        <pre className="error-boundary-detail">{String(error?.message || error)}</pre>
        {stack && (
          <details className="error-boundary-stack">
            <summary>Where it threw</summary>
            <pre>{stack}</pre>
          </details>
        )}
        <button className="primary" onClick={() => this.setState({ error: null, stack: null })}>
          Try again
        </button>
      </div>
    );
  }
}
