import hmac
import io
import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt

log = logging.getLogger(__name__)

# url name -> (management command, args). Keep args identical to deploy/connect.cron.
JOBS = {
    'close-stale-trips': ('close_stale_trips', []),
    'process-noshows': ('process_noshows', []),
    'expire-pending': ('expire_pending_bookings', []),
    'process-unapplied': ('process_unapplied', []),
    'reconcile-refunds': ('reconcile_refunds', []),
}
LOCK_TTL = 600  # seconds; a crashed run frees itself after this


@csrf_exempt
def run_job(request, job):
    secret = getattr(settings, 'CRON_SECRET', '')
    given = request.headers.get('X-Cron-Secret', '')
    # Every failure below is a plain 404 so outsiders learn nothing.
    if request.method != 'POST' or not secret:
        raise Http404
    if not hmac.compare_digest(given.encode(), secret.encode()):
        raise Http404
    spec = JOBS.get(job)
    if spec is None:
        raise Http404

    name, args = spec
    lock_key = f'cron-lock:{job}'
    if not cache.add(lock_key, '1', LOCK_TTL):
        return JsonResponse({'status': 'already_running', 'job': job}, status=202)

    out = io.StringIO()
    started = time.monotonic()
    try:
        call_command(name, *args, stdout=out, stderr=out)
    except Exception:
        log.exception('cron job %s failed', job)
        return JsonResponse({'status': 'error', 'job': job}, status=500)
    finally:
        cache.delete(lock_key)
    return JsonResponse({
        'status': 'ok',
        'job': job,
        'seconds': round(time.monotonic() - started, 2),
        'output': out.getvalue()[-2000:],
    })
