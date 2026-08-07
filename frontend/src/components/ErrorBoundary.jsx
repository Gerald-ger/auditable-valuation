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
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // keep the stack in the console for the dev who is about to go looking
    console.error('Render failed:', error, info?.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="error-boundary">
        <div className="error-boundary-title">This panel failed to render.</div>
        <p>
          The most common cause is a <strong>stale backend</strong>: if the API is still
          running an older build than the page, a response can arrive in a shape the UI
          does not expect. Restart the backend, then reload.
        </p>
        <pre className="error-boundary-detail">{String(error?.message || error)}</pre>
        <button className="primary" onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </div>
    );
  }
}
