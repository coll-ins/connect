import AsyncPanel from '../../components/ui/AsyncPanel';
import { when } from '../shared/serviceUtils';
import './SeatSummary.css';

// Every number comes from the server summary; nothing is summed in the browser.
export default function SeatSummary({ query }) {
  // A 200 without the summary shape must not render as blanks.
  const s = typeof query.data?.open_seats === 'number' ? query.data : null;
  const status = query.status === 'ready' && !s ? 'error' : query.status;
  return (
    <div className="seat-summary">
      <AsyncPanel status={status} onRetry={query.reload} title="seat details" loadingText="Loading seat details…">
        {s && (
          <>
            <dl className="seat-summary-grid">
              <div><dt>Booked</dt><dd>{s.confirmed_seats} of {s.capacity}</dd></div>
              <div><dt>Open</dt><dd>{s.open_seats}</dd></div>
              <div><dt>Boarded</dt><dd>{s.boarded_seats}</dd></div>
              <div>
                <dt>Held, awaiting payment</dt>
                <dd>
                  {s.pending_seats}
                  {s.pending_seats > 0 && s.pending_expires_at && (
                    <small> · earliest hold ends {when(s.pending_expires_at)}</small>
                  )}
                </dd>
              </div>
              <div>
                <dt>Online booking</dt>
                <dd>{s.online_open ? `Open until ${when(s.online_closes_at)}` : 'Closed'}</dd>
              </div>
              <div><dt>Walk-ups</dt><dd>{s.walkup_allowed ? 'Allowed' : 'Not allowed'}</dd></div>
            </dl>
            {s.by_stage?.length > 0 && (
              <ul className="seat-summary-stages" aria-label="Booked seats by stage">
                {s.by_stage.map((st) => (
                  <li key={st.stage_id}>{st.name}: {st.booked_seats}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </AsyncPanel>
    </div>
  );
}
