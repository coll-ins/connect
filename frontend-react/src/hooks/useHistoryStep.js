import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

// A wizard's step lives in the URL, so the phone's Back button goes back one
// step instead of leaving the form and losing every answer.
export default function useHistoryStep() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const step = Math.max(0, Number.parseInt(params.get('step') || '0', 10) || 0);

  // Answers are kept in memory only, so a reload starts again at step 1.
  useEffect(() => {
    if (params.has('step')) setParams({}, { replace: true });
  }, []);

  const goTo = (n) => setParams(n > 0 ? { step: String(n) } : {});
  return [step, goTo, () => navigate(-1)];
}
