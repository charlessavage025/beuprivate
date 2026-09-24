from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Shipment, ShipmentStatus, TrackingEvent
from .simulator import build_sim_route

ESTIMATED_DAYS_BY_SERVICE = {
    "OVERNIGHT": 1,
    "EXPRESS": 2,
    "GROUND": 4,
}


@transaction.atomic
def create_shipment(
    *,
    sender_name,
    sender_phone,
    sender_line1,
    sender_city,
    sender_state,
    sender_line2="",
    sender_postal_code="",
    sender_country="Nigeria",
    recipient_name,
    recipient_phone,
    recipient_line1,
    recipient_city,
    recipient_state,
    recipient_line2="",
    recipient_postal_code="",
    recipient_country="Nigeria",
    service_level: str,
    weight_kg,
    dimensions: str = "",
    declared_value=None,
    origin: str,
    destination: str,
    stops=None,
    created_by=None,
    created_at=None,
):
    """
    origin/destination/stops are plain hub/facility names typed in by hand —
    there is no Facility table to look them up in.

    stops: ordered list of intermediate stop names between origin and
    destination, as picked by the admin. If None (not just empty), a route is
    randomly generated instead (used by seed data, not the staff "new
    shipment" form, where an empty list means "direct, no waypoints").
    """
    created_at = created_at or timezone.now()

    shipment = Shipment(
        sender_name=sender_name,
        sender_phone=sender_phone,
        sender_line1=sender_line1,
        sender_line2=sender_line2,
        sender_city=sender_city,
        sender_state=sender_state,
        sender_postal_code=sender_postal_code,
        sender_country=sender_country or "Nigeria",
        recipient_name=recipient_name,
        recipient_phone=recipient_phone,
        recipient_line1=recipient_line1,
        recipient_line2=recipient_line2,
        recipient_city=recipient_city,
        recipient_state=recipient_state,
        recipient_postal_code=recipient_postal_code,
        recipient_country=recipient_country or "Nigeria",
        service_level=service_level,
        weight_kg=weight_kg,
        dimensions=dimensions,
        declared_value=declared_value,
        route=[],
    )

    days = ESTIMATED_DAYS_BY_SERVICE.get(service_level, 4)
    shipment.estimated_delivery = (created_at + timedelta(days=days)).date()
    shipment.save()

    if stops is None:
        shipment.route = build_sim_route(origin, destination)
    else:
        shipment.route = [origin, *stops, destination]
    shipment.save(update_fields=["route"])

    TrackingEvent.objects.create(
        shipment=shipment,
        event_type=ShipmentStatus.LABEL_CREATED,
        location=origin,
        timestamp=created_at,
        created_by=created_by,
    )

    return shipment
