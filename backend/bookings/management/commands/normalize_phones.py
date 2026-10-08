"""
Report (default) or apply the canonical Kenyan phone format (+2547XXXXXXXX)
on every user and driver. --apply is all-or-nothing: it refuses to change
anything while a blocker remains.

Blockers:
  * two rows of the same kind that would end up with the same number;
  * a driver whose number matches a user that is not a driver account of the
    same company. Normalising would newly link that user to the driver's
    identity in every endpoint that matches drivers by phone.
Numbers that are not recognisable Kenyan mobiles are listed and never changed.
"""
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from drivers.models import Driver
from users.phone import KENYA_MOBILE, canonical_phone


class Command(BaseCommand):
    help = 'Report or apply canonical phone numbers on users and drivers.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        User = get_user_model()
        rows = []   # (kind, pk, old, new, role, company_id)

        users = (
            User.objects.exclude(phone_number__isnull=True).exclude(phone_number='')
            .values('pk', 'phone_number', 'role', 'company_id')
        )
        for u in users:
            rows.append(('user', u['pk'], u['phone_number'],
                         canonical_phone(u['phone_number']), u['role'], u['company_id']))

        drivers = (
            Driver.objects.exclude(phone_number__isnull=True).exclude(phone_number='')
            .values('pk', 'phone_number', 'company_id')
        )
        for d in drivers:
            rows.append(('driver', d['pk'], d['phone_number'],
                         canonical_phone(d['phone_number']), 'driver', d['company_id']))

        groups = defaultdict(list)
        for r in rows:
            groups[(r[0], r[3])].append(r)

        blockers = []
        for (kind, number), group in groups.items():
            if len(group) > 1:
                blockers.append(
                    f'{kind}s {[g[1] for g in group]} would all become {number} '
                    f'(currently {[g[2] for g in group]})'
                )
        for (kind, number), group in groups.items():
            if kind != 'driver':
                continue
            for u in groups.get(('user', number), []):
                if u[4] != 'driver' or u[5] != group[0][5]:
                    blockers.append(
                        f'driver {group[0][1]} shares {number} with {u[4]} user {u[1]} '
                        f'(company {u[5]} vs {group[0][5]})'
                    )

        changes = [r for r in rows if r[3] != r[2]]
        unrecognised = [r for r in rows if not KENYA_MOBILE.match(r[3])]

        self.stdout.write(
            f'{len(rows)} number(s) checked; {len(changes)} to change; '
            f'{len(unrecognised)} unrecognised; {len(blockers)} blocker(s).'
        )
        for r in changes:
            self.stdout.write(f'  {r[0]} {r[1]}: {r[2]} -> {r[3]}')
        for r in unrecognised:
            self.stdout.write(f'  UNRECOGNISED (left as is): {r[0]} {r[1]}: {r[2]}')
        for b in blockers:
            self.stdout.write(self.style.ERROR(f'  BLOCKER: {b}'))

        if not options['apply']:
            self.stdout.write('Report only. Nothing changed. Use --apply once there are no blockers.')
            return
        if blockers:
            raise CommandError('Resolve the blockers above first. Nothing was changed.')

        with transaction.atomic():
            for kind, pk, _old, new, _role, _company in changes:
                model = User if kind == 'user' else Driver
                model.objects.filter(pk=pk).update(phone_number=new)
        self.stdout.write(self.style.SUCCESS(f'Normalised {len(changes)} phone number(s).'))
