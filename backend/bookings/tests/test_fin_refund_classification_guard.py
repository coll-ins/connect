from django.test import SimpleTestCase

from connect.paystack_extra import classify_failure


class ParcelError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class CharterError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


PAYSTACK_CHARGE = {"currency": "KES", "amount": 50000}


class RefundClassificationGuardTests(SimpleTestCase):
    def test_explicit_parcel_business_rejection_is_refunded(self):
        action, _, _ = classify_failure(
            ParcelError("Parcel is not awaiting payment.", 409),
            PAYSTACK_CHARGE,
        )
        self.assertEqual(action, "refund")

    def test_explicit_charter_business_rejection_is_refunded(self):
        action, _, _ = classify_failure(
            CharterError("Bus is already booked.", 409),
            PAYSTACK_CHARGE,
        )
        self.assertEqual(action, "refund")

    def test_statusless_parcel_error_is_not_auto_refunded(self):
        action, _, _ = classify_failure(
            ParcelError("Unknown parcel failure."),
            PAYSTACK_CHARGE,
        )
        self.assertEqual(action, "retry")

    def test_statusless_charter_error_is_not_auto_refunded(self):
        action, _, _ = classify_failure(
            CharterError("Unknown charter failure."),
            PAYSTACK_CHARGE,
        )
        self.assertEqual(action, "retry")

    def test_non_409_business_error_is_not_auto_refunded(self):
        for error_type in (ParcelError, CharterError):
            for status in (400, 429):
                with self.subTest(error=error_type.__name__, status=status):
                    action, _, _ = classify_failure(
                        error_type("Not a confirmed business rejection.", status),
                        PAYSTACK_CHARGE,
                    )
                    self.assertEqual(action, "retry")
