from tracking.models import ServiceLevel
from tracking.services import create_shipment

DEFAULT_SERVICE_LEVEL = ServiceLevel.GROUND


def address_fields(prefix, name="Ada Okafor", city="Lagos", state="Lagos"):
    return {
        f"{prefix}_name": name,
        f"{prefix}_phone": "+2348000000000",
        f"{prefix}_line1": "1 Test Street",
        f"{prefix}_city": city,
        f"{prefix}_state": state,
        f"{prefix}_postal_code": "100001",
        f"{prefix}_country": "Nigeria",
    }


def make_shipment(
    *,
    origin="Origin Hub",
    destination="Destination Hub",
    stops=(),
    service_level=DEFAULT_SERVICE_LEVEL,
    weight_kg="1.5",
    sender_name="Ada Okafor",
    sender_city="Lagos",
    sender_state="Lagos",
    recipient_name="Chidi Obi",
    recipient_city="Abuja",
    recipient_state="FCT",
    **overrides,
):
    """Creates a shipment with sensible defaults for every required field.
    `stops=()` (the default) means a direct route with no waypoints; pass
    stops=None to get a randomly generated route instead."""
    fields = {}
    fields.update(address_fields("sender", name=sender_name, city=sender_city, state=sender_state))
    fields.update(address_fields("recipient", name=recipient_name, city=recipient_city, state=recipient_state))
    fields.update(overrides)
    return create_shipment(
        **fields,
        service_level=service_level,
        weight_kg=weight_kg,
        origin=origin,
        destination=destination,
        stops=list(stops) if stops is not None else None,
    )
