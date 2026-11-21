from django.core.management import call_command
from django.core.management.base import BaseCommand

from wallets.sweeps import review_rows, sweep_payouts, sweep_topups


class Command(BaseCommand):
    help = 'Verify pending top-ups, resolve in-flight payouts, then check the wallet ledger.'

    def handle(self, *args, **options):
        checked, expired = sweep_topups()
        self.stdout.write(f'top-ups checked: {checked}, expired: {expired}')
        summary = sweep_payouts()
        self.stdout.write('payouts ' + ', '.join(f'{k}: {v}' for k, v in summary.items()))
        for row in review_rows():
            self.stdout.write(f'review: payout {row.pk} user {row.user_id} KES {row.amount} '
                              f'since {row.updated_at:%Y-%m-%d %H:%M} ({row.failure_reason})')
        call_command('check_wallet_ledger', stdout=self.stdout)
