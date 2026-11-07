// Cancelling a trip refunds every paid passenger and cannot be undone.
export function confirmTripCancel(status) {
  if (status !== 'cancelled') return true;
  return window.confirm(
    'Cancel this trip? Every paid passenger gets a full refund and every '
    + 'booking is cancelled. This cannot be undone.'
  );
}

export function tripCancelSummary(result) {
  const parts = [
    `Trip cancelled. ${result?.cancelled_bookings ?? 0} booking(s) cancelled, `
    + `${result?.refunds_started ?? 0} refund(s) started.`,
  ];
  if (result?.refunds_to_follow_up) {
    parts.push(
      `${result.refunds_to_follow_up} need a manual follow-up (cash or a failed refund).`
    );
  }
  return parts.join(' ');
}
