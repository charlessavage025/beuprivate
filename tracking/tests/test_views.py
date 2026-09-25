from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from tracking.models import Shipment, ShipmentStatus
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

    def test_toggle_email_row_flips_the_flag(self):
        self.client.login(username="staffer", password="pass12345")
        self.assertTrue(self.shipment.email_notifications_enabled)

        response = self.client.post(
            reverse("staff_toggle_email_row", args=[self.shipment.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertFalse(self.shipment.email_notifications_enabled)
        self.assertContains(response, "Email: Off")

        response = self.client.post(
            reverse("staff_toggle_email_row", args=[self.shipment.pk])
        )
        self.shipment.refresh_from_db()
        self.assertTrue(self.shipment.email_notifications_enabled)
        self.assertContains(response, "Email: On")

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

    def test_delete_shipment_row_removes_it(self):
        self.client.login(username="staffer", password="pass12345")
        pk = self.shipment.pk
        response = self.client.post(
            reverse("staff_delete_shipment_row", args=[pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertFalse(Shipment.objects.filter(pk=pk).exists())

    def test_delete_shipment_row_requires_staff(self):
        self.client.login(username="regular", password="pass12345")
        response = self.client.post(
            reverse("staff_delete_shipment_row", args=[self.shipment.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Shipment.objects.filter(pk=self.shipment.pk).exists())


class PasswordChangeViewTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="staffer", password="oldpass123", is_staff=True
        )

    def test_requires_login(self):
        response = self.client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_change_password_logs_in_with_new_password(self):
        self.client.login(username="staffer", password="oldpass123")
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "oldpass123",
                "new_password1": "brand-new-pass-456",
                "new_password2": "brand-new-pass-456",
            },
        )
        self.assertRedirects(response, reverse("password_change_done"))
        self.client.logout()
        self.assertTrue(
            self.client.login(username="staffer", password="brand-new-pass-456")
        )
