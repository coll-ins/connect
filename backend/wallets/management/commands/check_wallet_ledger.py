from django.core.management.base import BaseCommand, CommandError

from wallets import alerts
from wallets.sweeps import ledger_drift


class Command(BaseCommand):
    help = 'Read-only: verify every wallet balance equals the sum of its ledger.'

    def handle(self, *args, **options):
        drift = ledger_drift()
        if not drift:
            self.stdout.write('wallet ledger ok')
            return
        lines = [f'user {u}: balance {b}, ledger {t}' for u, b, t in drift]
        alerts.send(f'Wallet ledger drift on {len(drift)} wallet(s): ' + '; '.join(lines[:5]))
        raise CommandError('Wallet ledger drift:\n' + '\n'.join(lines))
