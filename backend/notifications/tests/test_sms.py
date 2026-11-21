from unittest import mock

from django.test import SimpleTestCase, override_settings

from notifications import sms

LOG = 'notifications.sms'


class FormatNumberTests(SimpleTestCase):
    def test_kenyan_spellings_become_e164(self):
        for raw, expected in (
            ('0712345678', '+254712345678'),
            ('0712 345 678', '+254712345678'),
            ('712345678', '+254712345678'),
            ('+254712345678', '+254712345678'),
            ('254712345678', '+254712345678'),   # was '+254254712345678'
            ('  +254 712 345 678 ', '+254712345678'),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(sms.format_number(raw), expected)


@override_settings(AT_API_KEY='k', AT_USERNAME='u', ADMIN_ALERT_PHONE_NUMBERS=['254700000001'])
class SendTests(SimpleTestCase):
    def patched_sdk(self):
        sdk = mock.MagicMock()
        return sdk, mock.patch.object(sms, 'africastalking', sdk)

    def test_booking_sms_goes_to_the_formatted_number_and_returns_true(self):
        sdk, patch = self.patched_sdk()
        with patch:
            self.assertTrue(sms.send_booking_sms('0712345678', 'BK-1'))
        sdk.initialize.assert_called_once_with(username='u', api_key='k')
        message, recipients = sdk.SMS.send.call_args.args
        self.assertEqual(recipients, ['+254712345678'])
        self.assertIn('BK-1', message)

    def test_a_gateway_failure_is_swallowed_so_money_code_continues(self):
        sdk, patch = self.patched_sdk()
        sdk.SMS.send.side_effect = RuntimeError('gateway down')
        with patch, self.assertLogs(LOG, level='ERROR'):
            self.assertFalse(sms.send_booking_sms('0712345678', 'BK-1'))

    def test_initialise_failure_is_swallowed_too(self):
        sdk, patch = self.patched_sdk()
        sdk.initialize.side_effect = RuntimeError('bad credentials')
        with patch, self.assertLogs(LOG, level='ERROR'):
            self.assertFalse(sms.send_driver_sms('0712345678', 'BK-1', 'D', '0700', 'KAA'))

    @override_settings(AT_API_KEY='')
    def test_no_key_sends_nothing_and_says_so(self):
        sdk, patch = self.patched_sdk()
        with patch, self.assertLogs(LOG, level='WARNING') as logs:
            self.assertFalse(sms.send_booking_sms('0712345678', 'BK-1'))
        sdk.SMS.send.assert_not_called()
        self.assertIn('AT_API_KEY is not configured', logs.output[0])

    def test_failure_log_carries_no_phone_number_or_message_text(self):
        sdk, patch = self.patched_sdk()
        sdk.SMS.send.side_effect = RuntimeError('gateway down')
        with patch, self.assertLogs(LOG, level='ERROR') as logs:
            sms.send_booking_sms('0712345678', 'BK-SECRET-9')
        text = ' '.join(logs.output)
        for private in ('0712345678', '712345678', 'BK-SECRET-9'):
            self.assertNotIn(private, text)

    def test_admin_alert_goes_to_every_configured_number(self):
        sdk, patch = self.patched_sdk()
        with patch, override_settings(ADMIN_ALERT_PHONE_NUMBERS=['0700000001', '254700000002']):
            self.assertTrue(sms.send_admin_alert_sms('refund stuck'))
        message, recipients = sdk.SMS.send.call_args.args
        self.assertEqual(recipients, ['+254700000001', '+254700000002'])
        self.assertTrue(message.startswith('CONNECT ALERT: '))

    @override_settings(ADMIN_ALERT_PHONE_NUMBERS=[])
    def test_admin_alert_without_numbers_is_logged_not_sent(self):
        sdk, patch = self.patched_sdk()
        with patch, self.assertLogs(LOG, level='ERROR'):
            self.assertFalse(sms.send_admin_alert_sms('refund stuck'))
        sdk.SMS.send.assert_not_called()

    def test_trip_cancelled_wording_depends_on_payment(self):
        sdk, patch = self.patched_sdk()
        with patch:
            sms.send_trip_cancelled_sms('0712345678', 'BK-1', 'R', paid=True)
            self.assertIn('full refund', sdk.SMS.send.call_args.args[0])
            sms.send_trip_cancelled_sms('0712345678', 'BK-1', 'R', paid=False)
            self.assertIn('not been charged', sdk.SMS.send.call_args.args[0])
