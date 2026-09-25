import random
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Shipment, ShipmentStatus, TrackingEvent

DELAY_REASONS = [
    "Weather delay",
    "Address verification needed",
    "Missed sort",
]

# Used only as a fallback when a shipment is created without an explicit
# route (e.g. seed data) so demo shipments still have varied routes. Plain
# strings — there is no Facility table to draw these from.
SAMPLE_WAYPOINT_NAMES = [
    "Lagos Hub",
    "Abuja Hub",
    "Port Harcourt Hub",
    "Kano Hub",
    "Ibadan Hub",
    "Enugu Sort Center",
    "Kaduna Sort Center",
]


def build_sim_route(origin: str, destination: str):
    candidates = [
        name for name in SAMPLE_WAYPOINT_NAMES if name not in (origin, destination)
    ]
    random.shuffle(candidates)
    num_waypoints = min(random.randint(1, 3), len(candidates))
    waypoints = candidates[:num_waypoints]
    return [origin, *waypoints, destination]


def _next_timestamp(prev_ts):
    now = timezone.now()
    candidate = prev_ts + timedelta(seconds=random.randint(3600, 21600))
    if candidate > now:
        candidate = now
    if candidate <= prev_ts:
        candidate = prev_ts + timedelta(seconds=1)
    return candidate


def _clamp_after(ts, prev_ts):
    """Keep a staff-picked timestamp strictly after the previous event's, so
    ordering (and the status-recompute that relies on it) stays consistent."""
    if ts <= prev_ts:
        return prev_ts + timedelta(seconds=1)
    return ts


def _next_route_location(route, current_location, visited_locations):
    """Location name to arrive at next, handling off-route recovery."""
    if current_location in route:
        idx = route.index(current_location)
        if idx + 1 < len(route):
            return route[idx + 1]
        return route[-1]

    # Off-route: resume after the furthest route stop already visited.
    furthest_idx = -1
    for location in visited_locations:
        if location in route:
            idx = route.index(location)
            furthest_idx = max(furthest_idx, idx)
    if furthest_idx + 1 < len(route):
        return route[furthest_idx + 1]
    return route[-1]


def _compute_next_step(shipment, reference_event):
    route = shipment.route
    event_type = reference_event.event_type
    location = reference_event.location

    if event_type == ShipmentStatus.LABEL_CREATED:
        return {
            "event_type": ShipmentStatus.PICKED_UP,
            "location": route[0] if route else location,
        }

    if event_type in (ShipmentStatus.PICKED_UP, ShipmentStatus.DEPARTED_FACILITY):
        visited = list(
            shipment.events.exclude(location="")
            .order_by("timestamp", "id")
            .values_list("location", flat=True)
        )
        next_location = _next_route_location(route, location, visited)
        return {
            "event_type": ShipmentStatus.ARRIVED_AT_FACILITY,
            "location": next_location,
        }

    if event_type == ShipmentStatus.ARRIVED_AT_FACILITY:
        destination = route[-1] if route else None
        if location == destination:
            return {
                "event_type": ShipmentStatus.OUT_FOR_DELIVERY,
                "location": location,
                "location_note": shipment.recipient_city,
            }
        return {
            "event_type": ShipmentStatus.DEPARTED_FACILITY,
            "location": location,
        }

    if event_type == ShipmentStatus.OUT_FOR_DELIVERY:
        return {
            "event_type": ShipmentStatus.DELIVERED,
            "location": location,
        }

    # Fallback: shouldn't normally be reached.
    return {"event_type": ShipmentStatus.PICKED_UP, "location": location}


@transaction.atomic
def advance(shipment: Shipment, timestamp=None):
    """timestamp, if given, overrides the auto-computed time for the new
    event (staff-picked via the date/time modal); it's clamped to land after
    the previous event so ordering stays consistent."""
    shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)

    latest = shipment.events.order_by("-timestamp", "-id").first()
    if latest is None or latest.event_type == ShipmentStatus.DELIVERED:
        return None

    delay_rate = getattr(settings, "SIM_DELAY_RATE", 0.05)
    new_ts = _clamp_after(timestamp, latest.timestamp) if timestamp else _next_timestamp(latest.timestamp)

    if latest.event_type == ShipmentStatus.DELAYED:
        reference = (
            shipment.events.exclude(event_type=ShipmentStatus.DELAYED)
            .order_by("-timestamp", "-id")
            .first()
        )
        if reference is None:
            reference = latest
        step = _compute_next_step(shipment, reference)
    else:
        if random.random() < delay_rate:
            return TrackingEvent.objects.create(
                shipment=shipment,
                event_type=ShipmentStatus.DELAYED,
                location=latest.location,
                delay_reason=random.choice(DELAY_REASONS),
                timestamp=new_ts,
            )
        step = _compute_next_step(shipment, latest)

    return TrackingEvent.objects.create(
        shipment=shipment,
        event_type=step["event_type"],
        location=step.get("location") or "",
        location_note=step.get("location_note", ""),
        timestamp=new_ts,
    )


@transaction.atomic
def rewind(shipment: Shipment):
    """Undo the shipment's latest scan, reverting it to its previous state.
    Deleting the event triggers the same status-recompute signal a normal
    delete does. Returns the deleted event, or None if there was nothing to
    undo (no events at all)."""
    shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
    latest = shipment.events.order_by("-timestamp", "-id").first()
    if latest is None:
        return None
    latest.delete()
    return latest


@transaction.atomic
def flag_delay(shipment: Shipment, reason="", timestamp=None):
    """Manually mark a shipment as DELAYED, independent of the random delay
    advance() sometimes rolls on its own. A later advance() call resumes the
    normal flow from wherever the shipment was before this. timestamp, if
    given, overrides the auto-computed time (staff-picked via the date/time
    modal)."""
    shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
    latest = shipment.events.order_by("-timestamp", "-id").first()
    if latest is not None and latest.event_type == ShipmentStatus.DELIVERED:
        return None
    if timestamp:
        new_ts = _clamp_after(timestamp, latest.timestamp) if latest else timestamp
    else:
        new_ts = _next_timestamp(latest.timestamp) if latest else timezone.now()
    return TrackingEvent.objects.create(
        shipment=shipment,
        event_type=ShipmentStatus.DELAYED,
        location=shipment.current_location,
        delay_reason=reason.strip() or "Flagged by staff",
        timestamp=new_ts,
    )


def advance_all():
    count = 0
    shipment_ids = Shipment.objects.exclude(
        status=ShipmentStatus.DELIVERED
    ).values_list("id", flat=True)
    for shipment_id in shipment_ids:
        shipment = Shipment.objects.get(pk=shipment_id)
        if advance(shipment) is not None:
            count += 1
    return count


def run_to_delivery(shipment: Shipment, max_steps=50):
    for _ in range(max_steps):
        shipment.refresh_from_db()
        if shipment.status == ShipmentStatus.DELIVERED:
            break
        result = advance(shipment)
        if result is None:
            break
    shipment.refresh_from_db()
    return shipment
