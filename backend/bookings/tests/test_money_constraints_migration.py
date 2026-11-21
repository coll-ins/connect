"""Migration 0029 adds the money CHECK constraints and refuses dirty data first."""
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from bookings.models import Booking, BookingHold, Payment
from companies.models import Company, Route
from users.models import CustomUser

BEFORE = [('bookings', '0031_late_payment_fields_idempotency')]
AFTER = [('bookings', '0032_money_check_constraints')]


class MoneyConstraintTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def make(self, apps, seats=1):
        Booking_, Payment_ = apps.get_model('bookings', 'Booking'), apps.get_model('bookings', 'Payment')
        user = CustomUser.objects.create(username='u', phone_number='+254711000009')
        company = Company.objects.create(name='C', areas_served='x')
        route = Route.objects.create(company=company, name='R', start_point='a',
                                     end_point='b', price=100)
        booking = Booking_.objects.create(
            user_id=user.pk, route_id=route.pk, seats=seats,
            total_amount=Decimal('100'), status='confirmed', pickup_location='x')
        return Booking_, Payment_, booking

    def test_dirty_rows_are_named_and_nothing_is_changed(self):
        apps = self.migrate(BEFORE)
        Booking_, Payment_, booking = self.make(apps)
        pay = Payment_.objects.create(
            booking_id=booking.pk, amount=Decimal('100'), method='digital',
            status='confirmed', refund_amount=Decimal('150'))
        with self.assertRaises(RuntimeError) as ctx:
            self.migrate(AFTER)
        self.assertIn(str(pay.pk), str(ctx.exception))
        self.assertIn('refund above the amount paid', str(ctx.exception))
        self.assertEqual(Payment_.objects.get(pk=pay.pk).refund_amount, Decimal('150'))
        Payment_.objects.filter(pk=pay.pk).update(refund_amount=Decimal('100'))

    def test_clean_data_migrates_and_the_constraints_hold(self):
        apps = self.migrate(BEFORE)
        self.make(apps)
        self.migrate(AFTER)
        # The models below are the current ones, so bring the schema up to them.
        self.tearDown()
        booking = Booking.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Payment.objects.create(
                booking=booking, amount=Decimal('100'), method='digital',
                status='confirmed', refund_amount=Decimal('100.01'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.filter(pk=booking.pk).update(seats=0)
        Payment.objects.create(
            booking=booking, amount=Decimal('100'), method='digital',
            status='confirmed', refund_amount=Decimal('100'))
        with self.assertRaises(IntegrityError), transaction.atomic():
            BookingHold.objects.create(booking=booking, amount=Decimal('100'),
                                       refunded_amount=Decimal('101'))

    def test_one_idempotency_key_per_user(self):
        self.migrate(AFTER)
        user = CustomUser.objects.create(username='k', phone_number='+254711000008')
        company = Company.objects.create(name='C2', areas_served='x')
        route = Route.objects.create(company=company, name='R2', start_point='a',
                                     end_point='b', price=100)
        kw = dict(user=user, route=route, total_amount=Decimal('100'),
                  pickup_location='x')
        Booking.objects.create(idempotency_key='k1', **kw)
        Booking.objects.create(idempotency_key=None, **kw)
        Booking.objects.create(idempotency_key=None, **kw)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.create(idempotency_key='k1', **kw)

    def test_the_migration_reverses(self):
        self.migrate(AFTER)
        apps = self.migrate(BEFORE)
        self.assertTrue(apps.get_model('bookings', 'Booking'))
