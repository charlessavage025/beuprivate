from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from tracking.models import ShipmentStatus, TrackingEvent
from tracking.simulator import advance, advance_all, flag_delay, rewind, run_to_delivery
from .factories import make_shipment


@override_settings(SIM_DELAY_RATE=0)
class AdvanceTests(TestCase):
    def setUp(self):
        self.origin = "Origin Hub"
        self.hub1 = "Hub One"
        self.hub2 = "Hub Two"
        self.destination = "Destination Hub"
        self.shipment = make_shipment(
            origin=self.origin,
            destination=self.destination,
            stops=[self.hub1, self.hub2],
            recipient_name="Chidi Obi",
            recipient_city="Abuja",
            recipient_state="FCT",
        )

    def test_walks_route_to_delivered_one_event_per_call(self):
        # LABEL_CREATED already exists; walking the full route to DELIVERED
        # takes: PICKED_UP, then ARRIVED (+DEPARTED for each non-final stop),
        # then OUT_FOR_DELIVERY, then DELIVERED.
        events_before = self.shipment.events.count()
        self.assertEqual(events_before, 1)

        result = advance(self.shipment)
        while result is not None:
            result = advance(self.shipment)

        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELIVERED)

        # Every stop in the route should have been visited (arrived) in order.
        arrived_locations = [
            e.location
            for e in self.shipment.events.filter(
                event_type=ShipmentStatus.ARRIVED_AT_FACILITY
            ).order_by("timestamp", "id")
        ]
        self.assertEqual(arrived_locations, self.shipment.route[1:])

    def test_creates_exactly_one_event_per_call(self):
        before = self.shipment.events.count()
        advance(self.shipment)
        after = self.shipment.events.count()
        self.assertEqual(after, before + 1)

    def test_returns_none_after_delivered(self):
        run_to_delivery(self.shipment)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELIVERED)
        self.assertIsNone(advance(self.shipment))

    def test_timestamps_strictly_increasing_and_not_in_future(self):
        now_before = timezone.now()
        prev_ts = self.shipment.latest_event().timestamp
        for _ in range(10):
            event = advance(self.shipment)
            if event is None:
                break
            self.assertGreater(event.timestamp, prev_ts)
            self.assertLessEqual(event.timestamp, timezone.now() + timedelta(seconds=1))
            prev_ts = event.timestamp
        self.assertGreaterEqual(prev_ts, now_before)

    def test_recovers_after_delay(self):
        latest = self.shipment.latest_event()
        TrackingEvent.objects.create(
            shipment=self.shipment,
            event_type=ShipmentStatus.DELAYED,
            location=latest.location,
            delay_reason="Weather delay",
            timestamp=latest.timestamp + timedelta(hours=1),
        )
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELAYED)

        event = advance(self.shipment)
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, ShipmentStatus.PICKED_UP)

    def test_recovers_after_manual_off_route_scan(self):
        # Manually scan the shipment as arrived at a location not in its route.
        off_route = "Some Other Hub"
        TrackingEvent.objects.create(
            shipment=self.shipment,
            event_type=ShipmentStatus.ARRIVED_AT_FACILITY,
            location=off_route,
            timestamp=self.shipment.latest_event().timestamp + timedelta(hours=1),
        )
        self.shipment.refresh_from_db()

        # Should not crash, and should keep making progress towards delivery.
        result = run_to_delivery(self.shipment, max_steps=50)
        self.assertEqual(result.status, ShipmentStatus.DELIVERED)


@override_settings(SIM_DELAY_RATE=0)
class AdminChosenRouteTests(TestCase):
    """The staff 'new shipment' form ties explicit, hand-typed stops to the
    shipment instead of a randomly generated hidden route."""

    def setUp(self):
        self.origin = "Origin Hub"
        self.stop_a = "Stop A"
        self.stop_b = "Stop B"
        self.destination = "Destination Hub"

    def test_route_stops_are_used_verbatim(self):
        shipment = make_shipment(
            origin=self.origin,
            destination=self.destination,
            stops=[self.stop_a, self.stop_b],
        )
        self.assertEqual(
            shipment.route,
            [self.origin, self.stop_a, self.stop_b, self.destination],
        )

    def test_advance_walks_the_admin_chosen_route_in_order(self):
        shipment = make_shipment(
            origin=self.origin,
            destination=self.destination,
            stops=[self.stop_a, self.stop_b],
        )
        result = run_to_delivery(shipment)
        self.assertEqual(result.status, ShipmentStatus.DELIVERED)

        arrived_locations = [
            e.location
            for e in shipment.events.filter(
                event_type=ShipmentStatus.ARRIVED_AT_FACILITY
            ).order_by("timestamp", "id")
        ]
        self.assertEqual(arrived_locations, [self.stop_a, self.stop_b, self.destination])

    def test_no_stops_given_falls_back_to_random_route(self):
        shipment = make_shipment(
            origin=self.origin, destination=self.destination, stops=None
        )
        self.assertEqual(shipment.route[0], self.origin)
        self.assertEqual(shipment.route[-1], self.destination)


class AdvanceAllAndRunToDeliveryTests(TestCase):
    def setUp(self):
        self.origin = "Origin Hub 2"
        self.destination = "Destination Hub 2"

    def _new_shipment(self):
        return make_shipment(
            origin=self.origin, destination=self.destination, service_level="EXPRESS"
        )

    @override_settings(SIM_DELAY_RATE=0)
    def test_advance_all_skips_delivered(self):
        s1 = self._new_shipment()
        s2 = self._new_shipment()
        run_to_delivery(s1)
        s1.refresh_from_db()
        self.assertEqual(s1.status, ShipmentStatus.DELIVERED)

        count = advance_all()
        self.assertEqual(count, 1)  # only s2 advances
        s2.refresh_from_db()
        self.assertEqual(s2.status, ShipmentStatus.PICKED_UP)

    @override_settings(SIM_DELAY_RATE=0)
    def test_run_to_delivery_ends_delivered(self):
        shipment = self._new_shipment()
        result = run_to_delivery(shipment)
        self.assertEqual(result.status, ShipmentStatus.DELIVERED)

    @override_settings(SIM_DELAY_RATE=0)
    def test_run_to_delivery_respects_step_cap(self):
        shipment = self._new_shipment()
        result = run_to_delivery(shipment, max_steps=1)
        self.assertEqual(result.status, ShipmentStatus.PICKED_UP)
        self.assertNotEqual(result.status, ShipmentStatus.DELIVERED)


@override_settings(SIM_DELAY_RATE=0)
class RewindTests(TestCase):
    def setUp(self):
        self.shipment = make_shipment(origin="Origin Hub", destination="Destination Hub")

    def test_rewind_undoes_latest_event(self):
        advance(self.shipment)  # LABEL_CREATED -> PICKED_UP
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.PICKED_UP)

        deleted = rewind(self.shipment)
        self.assertIsNotNone(deleted)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.LABEL_CREATED)

    def test_rewind_chain_matches_advance_chain_in_reverse(self):
        for _ in range(3):
            advance(self.shipment)
        self.shipment.refresh_from_db()
        forward_statuses = [e.event_type for e in self.shipment.events.order_by("timestamp")]

        for _ in range(3):
            rewind(self.shipment)
        self.shipment.refresh_from_db()
        remaining_statuses = [e.event_type for e in self.shipment.events.order_by("timestamp")]
        self.assertEqual(remaining_statuses, forward_statuses[:1])  # only LABEL_CREATED left

    def test_rewind_works_after_delivery(self):
        run_to_delivery(self.shipment)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELIVERED)

        rewind(self.shipment)
        self.shipment.refresh_from_db()
        self.assertNotEqual(self.shipment.status, ShipmentStatus.DELIVERED)
        self.assertIsNone(self.shipment.delivered_at)

    def test_rewind_with_no_events_returns_none(self):
        self.shipment.events.all().delete()
        self.assertIsNone(rewind(self.shipment))


@override_settings(SIM_DELAY_RATE=0)
class FlagDelayTests(TestCase):
    def setUp(self):
        self.shipment = make_shipment(origin="Origin Hub", destination="Destination Hub")

    def test_flag_delay_marks_delayed(self):
        event = flag_delay(self.shipment)
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, ShipmentStatus.DELAYED)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELAYED)

    def test_flag_delay_defaults_reason_when_none_given(self):
        event = flag_delay(self.shipment)
        self.assertEqual(event.delay_reason, "Flagged by staff")

    def test_flag_delay_uses_given_reason(self):
        event = flag_delay(self.shipment, reason="Truck breakdown")
        self.assertEqual(event.delay_reason, "Truck breakdown")

    def test_advance_resumes_normal_flow_after_flag_delay(self):
        advance(self.shipment)  # PICKED_UP
        flag_delay(self.shipment)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELAYED)

        advance(self.shipment)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.ARRIVED_AT_FACILITY)

    def test_flag_delay_does_nothing_once_delivered(self):
        run_to_delivery(self.shipment)
        result = flag_delay(self.shipment)
        self.assertIsNone(result)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.DELIVERED)
