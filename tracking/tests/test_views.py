from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from tracking.models import ShipmentStatus
from tracking.simulator import run_to_delivery
from .factories import make_shipment

User = get_user_model()


@override_settings(SIM_DELAY_RATE=0)
class TrackViewTests(TestCase):
    def setUp(self):
        self.shipment = make_shipment(origin="Origin Hub", destination="Destination Hub")

    def test_htmx_request_returns_partial(self):
        response = self.client.get(
            reverse("track_detail", args=[self.shipment.tracking_number]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        # Partial should not include the full document shell.
        self.assertNotContains(response, "<html")

    def test_normal_request_returns_full_page(self):
        response = self.client.get(
            reverse("track_detail", args=[self.shipment.tracking_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<html")
        self.assertContains(response, self.shipment.tracking_number)

    def test_unknown_number_shows_not_found(self):
        response = self.client.get(
            reverse("track_search"),
            {"tracking_number": "000000000000"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No shipment found")

    def test_search_redirects_when_found_non_htmx(self):
        response = self.client.get(
            reverse("track_search"),
            {"tracking_number": self.shipment.tracking_number},
        )
        self.assertRedirects(
            response,
            reverse("track_detail", args=[self.shipment.tracking_number]),
        )

    def test_search_hx_redirect_header_when_found_htmx(self):
        response = self.client.get(
            reverse("track_search"),
            {"tracking_number": self.shipment.tracking_number},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["HX-Redirect"],
            reverse("track_detail", args=[self.shipment.tracking_number]),
        )

    def test_timeline_partial_stops_polling_once_delivered(self):
        response = self.client.get(
            reverse("track_timeline", args=[self.shipment.tracking_number])
        )
        self.assertContains(response, "hx-trigger")

        run_to_delivery(self.shipment)
        response = self.client.get(
            reverse("track_timeline", args=[self.shipment.tracking_number])
        )
        self.assertNotContains(response, "hx-trigger")


@override_settings(SIM_DELAY_RATE=0)
class StaffViewTests(TestCase):
    def setUp(self):
        self.shipment = make_shipment(origin="Origin Hub", destination="Destination Hub")
        self.staff_user = User.objects.create_user(
            username="staffer", password="pass12345", is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username="regular", password="pass12345", is_staff=False
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("staff_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_dashboard_requires_staff(self):
        self.client.login(username="regular", password="pass12345")
        response = self.client.get(reverse("staff_dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_dashboard_accessible_to_staff(self):
        self.client.login(username="staffer", password="pass12345")
        response = self.client.get(reverse("staff_dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_valid_scan_creates_event(self):
        self.client.login(username="staffer", password="pass12345")
        events_before = self.shipment.events.count()
        response = self.client.post(
            reverse("staff_scan"),
            {
                "tracking_number": self.shipment.tracking_number,
                "event_type": ShipmentStatus.PICKED_UP,
                "location": "",
                "location_note": "",
                "delay_reason": "",
                "timestamp": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.shipment.events.count(), events_before + 1)

    def test_delivery_scan_records_who_actually_signed(self):
        self.client.login(username="staffer", password="pass12345")
        response = self.client.post(
            reverse("staff_scan"),
            {
                "tracking_number": self.shipment.tracking_number,
                "event_type": ShipmentStatus.DELIVERED,
                "location": "",
                "location_note": "",
                "delay_reason": "",
                "signed_by": "James (security desk)",
                "timestamp": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELIVERED)
        self.assertEqual(self.shipment.signed_by, "James (security desk)")

    def test_delivery_scan_without_signed_by_defaults_to_recipient(self):
        self.client.login(username="staffer", password="pass12345")
        response = self.client.post(
            reverse("staff_scan"),
            {
                "tracking_number": self.shipment.tracking_number,
                "event_type": ShipmentStatus.DELIVERED,
                "location": "",
                "location_note": "",
                "delay_reason": "",
                "signed_by": "",
                "timestamp": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(
            self.shipment.signed_by, self.shipment.recipient_name.split(" ")[0]
        )

    def test_scan_on_delivered_shipment_rejected(self):
        run_to_delivery(self.shipment)
        self.client.login(username="staffer", password="pass12345")
        events_before = self.shipment.events.count()
        response = self.client.post(
            reverse("staff_scan"),
            {
                "tracking_number": self.shipment.tracking_number,
                "event_type": ShipmentStatus.PICKED_UP,
                "location": "",
                "location_note": "",
                "delay_reason": "",
                "timestamp": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.shipment.events.count(), events_before)
        self.assertContains(response, "already been delivered")

    def test_arrived_scan_requires_location(self):
        self.client.login(username="staffer", password="pass12345")
        response = self.client.post(
            reverse("staff_scan"),
            {
                "tracking_number": self.shipment.tracking_number,
                "event_type": ShipmentStatus.ARRIVED_AT_FACILITY,
                "location": "",
                "location_note": "",
                "delay_reason": "",
                "timestamp": "",
            },
        )
        self.assertContains(response, "location/facility name is required")

    def test_delayed_scan_requires_reason(self):
        self.client.login(username="staffer", password="pass12345")
        response = self.client.post(
            reverse("staff_scan"),
            {
                "tracking_number": self.shipment.tracking_number,
                "event_type": ShipmentStatus.DELAYED,
                "location": "",
                "location_note": "",
                "delay_reason": "",
                "timestamp": "",
            },
        )
        self.assertContains(response, "A reason is required")

    def test_delayed_scan_with_reason_creates_event_and_logs_reason(self):
        self.client.login(username="staffer", password="pass12345")
        response = self.client.post(
            reverse("staff_scan"),
            {
                "tracking_number": self.shipment.tracking_number,
                "event_type": ShipmentStatus.DELAYED,
                "location": "",
                "location_note": "",
                "delay_reason": "Truck breakdown",
                "timestamp": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELAYED)
        self.assertEqual(self.shipment.latest_event().delay_reason, "Truck breakdown")

    def test_rewind_row_undoes_latest_event(self):
        self.client.login(username="staffer", password="pass12345")
        from tracking.simulator import advance

        advance(self.shipment)  # LABEL_CREATED -> PICKED_UP
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.PICKED_UP)

        response = self.client.post(
            reverse("staff_rewind_row", args=[self.shipment.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.LABEL_CREATED)

    def test_rewind_row_works_on_delivered_shipment(self):
        self.client.login(username="staffer", password="pass12345")
        run_to_delivery(self.shipment)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELIVERED)

        response = self.client.post(
            reverse("staff_rewind_row", args=[self.shipment.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertNotEqual(self.shipment.status, ShipmentStatus.DELIVERED)

    def test_flag_delay_row_marks_delayed(self):
        self.client.login(username="staffer", password="pass12345")
        response = self.client.post(
            reverse("staff_flag_delay_row", args=[self.shipment.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELAYED)

    def test_flag_delay_row_logs_prompted_reason(self):
        self.client.login(username="staffer", password="pass12345")
        response = self.client.post(
            reverse("staff_flag_delay_row", args=[self.shipment.pk]),
            HTTP_HX_PROMPT="Truck broke down on the highway",
        )
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(
            self.shipment.latest_event().delay_reason,
            "Truck broke down on the highway",
        )

    def test_flag_delay_row_ignored_once_delivered(self):
        self.client.login(username="staffer", password="pass12345")
        run_to_delivery(self.shipment)
        response = self.client.post(
            reverse("staff_flag_delay_row", args=[self.shipment.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELIVERED)

    def test_create_shipment_form_ties_typed_route_to_shipment(self):
        self.client.login(username="staffer", password="pass12345")
        response = self.client.post(
            reverse("staff_shipment_new"),
            {
                "sender_name": "Emeka Nwosu",
                "sender_phone": "+2348033333333",
                "sender_line1": "14 Marina Road",
                "sender_line2": "",
                "sender_city": "Lagos",
                "sender_state": "Lagos",
                "sender_postal_code": "",
                "sender_country": "Nigeria",
                "recipient_name": "Fatima Bello",
                "recipient_phone": "+2348044444444",
                "recipient_email": "fatima.bello@example.com",
                "recipient_line1": "7 Ahmadu Bello Way",
                "recipient_line2": "",
                "recipient_city": "Kaduna",
                "recipient_state": "Kaduna",
                "recipient_postal_code": "",
                "recipient_country": "Nigeria",
                "service_level": "EXPRESS",
                "weight_kg": "3.2",
                "dimensions": "",
                "declared_value": "",
                "origin": "Lagos Hub",
                "destination": "Kaduna Sort Center",
                "stops": "Ibadan Hub\nAbuja Hub",
            },
        )
        self.assertEqual(response.status_code, 302)
        from tracking.models import Shipment

        shipment = Shipment.objects.latest("created_at")
        self.assertEqual(
            shipment.route,
            ["Lagos Hub", "Ibadan Hub", "Abuja Hub", "Kaduna Sort Center"],
        )
