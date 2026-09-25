from django.core import mail
from django.test import TestCase

from tracking.models import ShipmentStatus, TrackingEvent
from .factories import make_shipment


class EventNotificationEmailTests(TestCase):
    def setUp(self):
        self.shipment = make_shipment(
            origin="Origin Hub", destination="Destination Hub"
        )
        mail.outbox = []

    def _create_event(self, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            TrackingEvent.objects.create(
                shipment=self.shipment,
                event_type=ShipmentStatus.PICKED_UP,
                **kwargs,
            )

    def test_email_sent_when_enabled_and_address_on_file(self):
        self._create_event()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.shipment.tracking_number, mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [self.shipment.recipient_email])

    def test_no_email_when_notifications_disabled(self):
        self.shipment.email_notifications_enabled = False
        self.shipment.save(update_fields=["email_notifications_enabled"])

        self._create_event()
        self.assertEqual(len(mail.outbox), 0)

    def test_no_email_when_no_recipient_address_on_file(self):
        self.shipment.recipient_email = ""
        self.shipment.save(update_fields=["recipient_email"])

        self._create_event()
        self.assertEqual(len(mail.outbox), 0)

    def test_deleting_an_event_does_not_send_an_email(self):
        self._create_event()
        mail.outbox = []

        with self.captureOnCommitCallbacks(execute=True):
            self.shipment.events.order_by("-timestamp", "-id").first().delete()
        self.assertEqual(len(mail.outbox), 0)
