from django.test import TestCase

from tracking.forms import ShipmentCreateForm


def _base_form_data(origin, destination, **extra):
    data = {
        "sender_name": "Ada Okafor",
        "sender_phone": "+2348011111111",
        "sender_line1": "1 Test Street",
        "sender_city": "Lagos",
        "sender_state": "Lagos",
        "sender_country": "Nigeria",
        "recipient_name": "Chidi Obi",
        "recipient_phone": "+2348022222222",
        "recipient_line1": "2 Test Street",
        "recipient_city": "Abuja",
        "recipient_state": "FCT",
        "recipient_country": "Nigeria",
        "service_level": "GROUND",
        "weight_kg": "1.5",
        "origin": origin,
        "destination": destination,
        "stops": "",
    }
    data.update(extra)
    return data


class ShipmentCreateFormRouteTests(TestCase):
    def setUp(self):
        self.origin = "Origin Hub"
        self.stop_a = "Stop A"
        self.stop_b = "Stop B"
        self.destination = "Destination Hub"

    def test_valid_with_no_stops_typed(self):
        form = ShipmentCreateForm(data=_base_form_data(self.origin, self.destination))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.route_stops(), [])

    def test_valid_with_ordered_stops(self):
        data = _base_form_data(
            self.origin,
            self.destination,
            stops=f"{self.stop_a}\n{self.stop_b}",
        )
        form = ShipmentCreateForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.route_stops(), [self.stop_a, self.stop_b])

    def test_rejects_duplicate_stop_in_route(self):
        data = _base_form_data(
            self.origin,
            self.destination,
            stops=f"{self.stop_a}\n{self.stop_a}",
        )
        form = ShipmentCreateForm(data=data)
        self.assertFalse(form.is_valid())

    def test_rejects_stop_matching_origin(self):
        data = _base_form_data(
            self.origin,
            self.destination,
            stops=self.origin,
        )
        form = ShipmentCreateForm(data=data)
        self.assertFalse(form.is_valid())

    def test_rejects_origin_same_as_destination(self):
        data = _base_form_data(self.origin, self.origin)
        form = ShipmentCreateForm(data=data)
        self.assertFalse(form.is_valid())
