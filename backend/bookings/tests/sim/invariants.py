"""Global invariants, checked after every simulated scenario.

Each check appends a readable line to `problems`; the assertion fails once with
all of them, so one scenario never hides a second violation.
"""
import datetime as dt

from django.db.models import Q, Sum
from django.utils import timezone

from bookings import services
from bookings.models import Booking, Payment, Payout
from companies.models import Company, Trip
from wallets import sweeps
from wallets.models import Wallet, WalletPayout, WalletTransaction


def settle_all(tc):
    """What the scheduled jobs do once the outage is over: every sweep, with the gateway healthy."""
    tc.fake.clear_faults()
    tc.run_command('expire_pending_bookings')
    tc.run_command('process_noshows')
    tc.run_command('process_unapplied')
    sweeps.sweep_topups()
    sweeps.sweep_payouts(now=timezone.now() + dt.timedelta(minutes=5))


def assert_world_invariants(tc, settle=True):
    if settle:
        settle_all(tc)
    problems = []
    fake = tc.fake

    # 1. No oversold trip.
    for trip in Trip.objects.all():
        taken = services.seats_taken(trip)
        hard = (trip.bookings.filter(status__in=('confirmed', 'completed', 'no_show'))
                .aggregate(s=Sum('seats'))['s'] or 0)
        if taken > trip.capacity or hard > trip.capacity:
            problems.append(f'oversold trip {trip.pk}: taken {taken}, paid {hard}, capacity {trip.capacity}')

    # 2. Ledger sum == wallet balance; no negative balance.
    for user_id, balance, ledger in sweeps.ledger_drift():
        problems.append(f'ledger drift user {user_id}: balance {balance}, ledger {ledger}')
    for wallet in Wallet.objects.filter(Q(available_balance__lt=0) | Q(held_balance__lt=0)):
        problems.append(f'negative wallet {wallet.pk}: {wallet.available_balance}/{wallet.held_balance}')

    # 3. Refund totals per charge (DB view).
    for payment in Payment.objects.filter(method='digital').exclude(provider_reference__isnull=True).select_related('booking'):
        paid, refunded = services.charge_refund_totals(payment)
        if refunded > paid:
            problems.append(f'over-refunded {payment.provider_reference}: refunded {refunded} > paid {paid}')
        if payment.refund_reason == 'late_payment' and payment.booking.status == 'cancelled' and refunded != paid:
            problems.append(f'late payment {payment.provider_reference} not fully refunded: {refunded} of {paid}')
        if payment.status == 'confirmed' and payment.booking.status == 'pending':
            problems.append(f'payment confirmed but booking pending: {payment.provider_reference}')

    # 4. Gateway truth: never more refunded than charged, one refund per (charge, reason).
    seen = {}
    for refund in fake.accepted_refunds():
        key = (refund['transaction'], refund['kind'])
        seen[key] = seen.get(key, 0) + 1
    for (reference, kind), count in seen.items():
        if count > 1:
            problems.append(f'{count} accepted {kind} refunds on {reference}')
    for reference, charge in fake.charges.items():
        paid = charge['paid'] or 0
        if fake.refunded_subunits(reference) > paid:
            problems.append(f'gateway refunded more than charged on {reference}')

    # 5. One refund ledger row per payment (wallet payments), enforced by the unique reference.
    refunds = WalletTransaction.objects.filter(type='refund')
    if refunds.values('reference').distinct().count() != refunds.count():
        problems.append('two wallet refund rows with one reference')

    # 6. Every withdrawal has exactly one wd: row; a wdrev: row exists iff it failed.
    for payout in WalletPayout.objects.all():
        wd = WalletTransaction.objects.filter(reference=f'wd:{payout.pk}').count()
        rev = WalletTransaction.objects.filter(reference=f'wdrev:{payout.pk}').count()
        if wd != 1:
            problems.append(f'payout {payout.pk} has {wd} wd: rows')
        if rev != (1 if payout.status == 'failed' else 0):
            problems.append(f'payout {payout.pk} is {payout.status} with {rev} wdrev: rows')

    # 7. Settlement never pays a company twice, and never pays a refunded fare.
    for payment in Payment.objects.filter(payout__isnull=False).select_related('booking'):
        full_refund = (payment.refund_status == 'processed'
                       and payment.refund_amount is not None
                       and payment.refund_amount >= payment.amount)
        if payment.status != 'confirmed' or full_refund or payment.settlement_status != 'settled':
            problems.append(f'payment {payment.pk} in payout {payment.payout_id} but '
                            f'{payment.status}/{payment.settlement_status}/refund {payment.refund_status}')
    for payout in Payout.objects.all():
        wrong = Payment.objects.filter(payout=payout).exclude(booking__route__company=payout.company).count()
        if wrong:
            problems.append(f'payout {payout.reference} includes {wrong} payment(s) of another company')

    # 8. No gateway call inside a transaction; nothing escaped the fake.
    for call in fake.calls_inside_atomic():
        if call['endpoint'] != 'sms':
            problems.append(f"gateway call inside atomic: {call['method']} {call['path']}")
    for leak in fake.leaks:
        problems.append(f"unexpected outbound request: {leak['method']} {leak['url']}")

    # 9. Company A staff never see company B.
    problems.extend(isolation_problems(tc))

    if problems:
        tc.fail('world invariants violated:\n  ' + '\n  '.join(problems))


# ------------------------------------------------------------------ isolation

def isolation_problems(tc):
    from django.urls import reverse

    problems = []
    companies = list(Company.objects.all())
    for a in companies:
        for other in companies:
            if other.pk == a.pk:
                continue
            theirs = list(Booking.objects.filter(route__company=other).select_related('trip__driver')[:6])
            if not theirs:
                continue
            numbers = {b.booking_number for b in theirs}
            before = {b.pk: b.status for b in theirs}
            for role in ('company_manager', 'company_operator', 'company_auditor'):
                client = tc.api(tc.staff(a, role))
                for name in ('bookings:get-all-bookings', 'bookings:auditor-receipt-search',
                             'bookings:staff-alerts', 'bookings:incident-list',
                             'bookings:passenger-records'):
                    body = client.get(reverse(name)).content.decode('utf-8', 'replace')
                    leaked = [n for n in numbers if n in body]
                    if leaked:
                        problems.append(f'{role} of {a.name} sees {other.name} bookings via {name}: {leaked[:2]}')
                for b in theirs[:1]:
                    for name, method in (
                            ('bookings:get-booking-detail', 'get'),
                            ('bookings:booking-live-location', 'get'),
                            ('bookings:cancel-booking', 'post'),
                            ('bookings:verify-boarding', 'post')):
                        r = getattr(client, method)(reverse(name, args=[b.pk]), {'boarding_pin': '000000'}, format='json') \
                            if method == 'post' else client.get(reverse(name, args=[b.pk]))
                        if r.status_code not in (403, 404):
                            problems.append(f'{role} of {a.name}: {method.upper()} {name} on {other.name} booking -> {r.status_code}')
                    if b.trip_id:
                        r = client.get(reverse('trip-seat-summary', args=[b.trip_id]))
                        if r.status_code not in (403, 404):
                            problems.append(f'{role} of {a.name}: seat-summary of {other.name} trip -> {r.status_code}')
                        r = client.post(reverse('update_trip_status', args=[b.trip_id]), {'status': 'cancelled'}, format='json')
                        if r.status_code not in (403, 404):
                            problems.append(f'{role} of {a.name}: trip status of {other.name} -> {r.status_code}')
                    driver_id = b.trip.driver_id if b.trip_id else None
                    if driver_id:
                        r = client.get(reverse('drivers:driver-location', args=[driver_id]))
                        if r.status_code not in (403, 404):
                            problems.append(f'{role} of {a.name}: driver location of {other.name} -> {r.status_code}')
            after = {b.pk: b.status for b in Booking.objects.filter(pk__in=before)}
            if after != before:
                problems.append(f'staff of {a.name} changed {other.name} bookings: {before} -> {after}')
    return problems
