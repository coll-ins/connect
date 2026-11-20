import { Component } from 'react';
import '../styles/states.css';

export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Always logged: the fallback copy must not hide the cause from developers.
    console.error('Uncaught render error', error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="error-boundary" role="alert">
        <h1>Something went wrong</h1>
        <p>Reload the page.</p>
        <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
          Reload
        </button>
        {import.meta.env.DEV && <pre>{String(this.state.error?.stack || this.state.error)}</pre>}
      </main>
    );
  }
}
