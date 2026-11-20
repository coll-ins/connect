from . import payouts, topup


def handle_event(event):
    """
    Paystack webhook hook, called before the booking lookup. True when the
    event was ours (a TOPUP- charge or a wd- transfer) and must not reach the booking code.
    transfer.* is handled whatever WALLET_PAYOUTS_ENABLED says: money in flight must finalise.
    """
    if event.get('event') in payouts.EVENT_ACTIONS:
        return payouts.apply_transfer_event(event['event'], event.get('data'))
    if event.get('event') != 'charge.success':
        return False
    data = event.get('data') or {}
    reference = data.get('reference')
    if not isinstance(reference, str) or not reference.startswith(topup.TOPUP_PREFIX):
        return False
    topup.apply_topup_charge(reference, data)
    return True
