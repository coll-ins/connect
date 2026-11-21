from django.core.management.base import BaseCommand, CommandError

from wallets import payouts


class Command(BaseCommand):
    help = ('Settle one payout stuck in review, once. --paid: Paystack really paid it. '
            '--reverse: it did not leave, credit the wallet back. Check Paystack first.')

    def add_arguments(self, parser):
        parser.add_argument('payout_id', type=int)
        parser.add_argument('--paid', action='store_true')
        parser.add_argument('--reverse', action='store_true')

    def handle(self, *args, **options):
        if options['paid'] == options['reverse']:
            raise CommandError('Pass exactly one of --paid or --reverse.')
        action = 'paid' if options['paid'] else 'reverse'
        try:
            payouts.resolve_review(options['payout_id'], action)
        except payouts.WalletPayout.DoesNotExist:
            raise CommandError('No such payout.')
        except ValueError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f'payout {options["payout_id"]} resolved: {action}')
