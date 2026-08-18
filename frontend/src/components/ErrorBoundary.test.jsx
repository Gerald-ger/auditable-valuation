/**
 * @vitest-environment jsdom
 *
 * The component whose whole job is to be the last line of defence, and which had
 * never been rendered by a test.
 *
 * Its docstring records what it exists for: a render-time throw unmounts the
 * entire React tree, so the app went completely black with no message. If this
 * boundary is itself broken the failure is silent in the worst way — nothing
 * reports it, because the thing that would have reported it is the thing that
 * broke.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import ErrorBoundary from './ErrorBoundary';
import { render, click } from '../test-utils';

const Boom = ({ message }) => {
  throw new Error(message);
};

const Healthy = () => <p className="healthy">rendered fine</p>;

let consoleError;

beforeEach(() => {
  // The boundary logs the stack on purpose (ErrorBoundary.jsx:28) and React logs
  // its own. Silenced so a passing run is quiet, and spied so the deliberate one
  // can be asserted.
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  consoleError.mockRestore();
});

describe('when nothing throws', () => {
  it('renders its children untouched', () => {
    const { container, unmount } = render(
      <ErrorBoundary><Healthy /></ErrorBoundary>,
    );
    expect(container.querySelector('.healthy')).not.toBeNull();
    expect(container.querySelector('.error-boundary')).toBeNull();
    unmount();
  });
});

describe('when a child throws during render', () => {
  it('replaces the subtree with the fallback instead of blanking the page', () => {
    const { container, unmount } = render(
      <ErrorBoundary><Boom message="bars is undefined" /></ErrorBoundary>,
    );
    // The point of the whole component: something is on screen.
    expect(container.querySelector('.error-boundary-title')).not.toBeNull();
    expect(container.textContent).toContain('stale backend');
    unmount();
  });

  it('shows the thrown message, so the reader has something to act on', () => {
    const { container, unmount } = render(
      <ErrorBoundary><Boom message="bars is undefined" /></ErrorBoundary>,
    );
    expect(container.querySelector('.error-boundary-detail').textContent)
      .toBe('bars is undefined');
    unmount();
  });

  it('renders a thrown non-Error as itself, not as [object Object]', () => {
    // `String(error?.message || error)` is the branch under test. A throw that is
    // not an Error has no `.message`, and a naive `String(error)` on an object
    // would print [object Object] — a fallback that reports nothing is the same
    // blank screen this component exists to prevent.
    const ThrowsString = () => {
      throw 'stream_failed';
    };
    const { container, unmount } = render(
      <ErrorBoundary><ThrowsString /></ErrorBoundary>,
    );
    expect(container.querySelector('.error-boundary-detail').textContent)
      .toBe('stream_failed');
    unmount();
  });

  it('logs the failure for whoever is about to go looking', () => {
    const { unmount } = render(
      <ErrorBoundary><Boom message="bars is undefined" /></ErrorBoundary>,
    );
    expect(consoleError).toHaveBeenCalledWith(
      'Render failed:', expect.any(Error), expect.anything());
    unmount();
  });
});

describe('Try again', () => {
  it('clears the error so a recovered subtree renders again', () => {
    const { container, rerender, unmount } = render(
      <ErrorBoundary><Boom message="bars is undefined" /></ErrorBoundary>,
    );
    expect(container.querySelector('.error-boundary')).not.toBeNull();

    // The realistic sequence: the underlying cause is fixed (the backend is
    // restarted, so the next render gets a well-formed response), and only then
    // does the button do anything. Clicking while the child still throws just
    // re-enters the fallback.
    rerender(<ErrorBoundary><Healthy /></ErrorBoundary>);
    expect(container.querySelector('.error-boundary')).not.toBeNull();

    click(container.querySelector('button.primary'));
    expect(container.querySelector('.healthy')).not.toBeNull();
    expect(container.querySelector('.error-boundary')).toBeNull();
    unmount();
  });
});
