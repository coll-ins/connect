import { useCallback, useEffect, useRef, useState } from 'react';
import { deriveStatus } from '../utils/loadStatus';

/**
 * Page-load fetch with the loading | error | ready state, a stable reload and
 * stale-response protection. Page loads are `silent`: the inline Retry panel
 * replaces the global toast, which stays for action failures.
 */
export default function useAsyncData(load, deps = []) {
  const [state, setState] = useState({ data: undefined, error: '', loading: true });
  const run = useRef(0);
  const loadRef = useRef(load);
  useEffect(() => { loadRef.current = load; });

  const reload = useCallback(() => {
    const id = run.current + 1;
    run.current = id;
    setState((s) => ({ ...s, loading: true, error: '' }));
    return Promise.resolve()
      .then(() => loadRef.current())
      .then(
        (data) => { if (run.current === id) setState({ data, error: '', loading: false }); },
        (e) => {
          if (run.current === id) {
            setState((s) => ({ ...s, error: e?.message || 'Request failed', loading: false }));
          }
        },
      );
  }, []);

  // A changed input (another company, say) must not show the old answer while
  // the new one loads; a manual reload() keeps what is on screen.
  useEffect(() => {
    setState({ data: undefined, error: '', loading: true });
    reload();
    return () => { run.current += 1; };
  }, [reload, ...deps]);

  const status = deriveStatus({
    loading: state.loading,
    error: state.error,
    hasData: state.data !== undefined,
  });
  return { status, data: state.data, error: state.error, reload };
}
