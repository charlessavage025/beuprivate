import random

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone


class ShipmentStatus(models.TextChoices):
    LABEL_CREATED = "LABEL_CREATED", "Label Created"
    PICKED_UP = "PICKED_UP", "Picked Up"
    ARRIVED_AT_FACILITY = "ARRIVED_AT_FACILITY", "Arrived at Facility"
    DEPARTED_FACILITY = "DEPARTED_FACILITY", "Departed Facility"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", "Out for Delivery"
    DELIVERED = "DELIVERED", "Delivered"
    DELAYED = "DELAYED", "Delayed"


class ServiceLevel(models.TextChoices):
    OVERNIGHT = "OVERNIGHT", "Overnight"
    EXPRESS = "EXPRESS", "Express"
    GROUND = "GROUND", "Ground"


DEFAULT_EVENT_DESCRIPTIONS = {
    ShipmentStatus.LABEL_CREATED: "Shipping label created",
    ShipmentStatus.PICKED_UP: "Package picked up",
    ShipmentStatus.ARRIVED_AT_FACILITY: "Arrived at facility",
    ShipmentStatus.DEPARTED_FACILITY: "Departed facility",
    ShipmentStatus.OUT_FOR_DELIVERY: "Out for delivery",
    ShipmentStatus.DELIVERED: "Delivered",
    ShipmentStatus.DELAYED: "Shipment delayed",
}


def generate_tracking_number():
    return "".join(random.choices("0123456789", k=12))


class Shipment(models.Model):
    tracking_number = models.CharField(
        max_length=12, unique=True, db_index=True, blank=True
    )

    # Sender / recipient are plain fields entered by hand at creation time —
    # not a FK to a separate Address model.
    sender_name = models.CharField(max_length=255)
    sender_phone = models.CharField(max_length=32)
    sender_line1 = models.CharField(max_length=255)
    sender_line2 = models.CharField(max_length=255, blank=True)
    sender_city = models.CharField(max_length=128)
    sender_state = models.CharField(max_length=128)
    sender_postal_code = models.CharField(max_length=32, blank=True)
    sender_country = models.CharField(max_length=128, default="Nigeria")

    recipient_name = models.CharField(max_length=255)
    recipient_phone = models.CharField(max_length=32)
    recipient_line1 = models.CharField(max_length=255)
    recipient_line2 = models.CharField(max_length=255, blank=True)
    recipient_city = models.CharField(max_length=128)
    recipient_state = models.CharField(max_length=128)
    recipient_postal_code = models.CharField(max_length=32, blank=True)
    recipient_country = models.CharField(max_length=128, default="Nigeria")

    service_level = models.CharField(max_length=16, choices=ServiceLevel.choices)
    weight_kg = models.DecimalField(max_digits=8, decimal_places=2)
    dimensions = models.CharField(max_length=64, blank=True)
    declared_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    # Ordered list of facility/hub names (plain strings, typed in by hand) this
    # shipment will stop at. route[0] is the origin, route[-1] the destination.
    # This is the planned path the simulator walks; it is NOT a lookup into any
    # other table — there is no separate Facility model.
    route = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=32,
        choices=ShipmentStatus.choices,
        default=ShipmentStatus.LABEL_CREATED,
        db_index=True,
    )
    # Cached copy of the latest event's location name (a free-text string, not
    # a relation), kept in sync from TrackingEvent history.
    current_location = models.CharField(max_length=255, blank=True)

    estimated_delivery = models.DateField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.tracking_number:
            for _ in range(10):
                candidate = generate_tracking_number()
                if not Shipment.objects.filter(
                    tracking_number=candidate
                ).exists():
                    self.tracking_number = candidate
                    break
            else:
                raise RuntimeError(
                    "Could not generate a unique tracking number"
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.tracking_number

    @property
    def origin(self):
        return self.route[0] if self.route else ""

    @property
    def destination(self):
        return self.route[-1] if self.route else ""

    def latest_event(self):
        return self.events.order_by("-timestamp", "-id").first()

    def visited_locations(self):
        """Ordered list of location names visited, collapsing consecutive dupes."""
        events = self.events.exclude(location="").order_by("timestamp", "id")
        stops = []
        for event in events:
            if not stops or stops[-1] != event.location:
                stops.append(event.location)
        return stops

    def stop_count(self):
        return len(self.visited_locations())

    def is_overdue(self):
        if self.status == ShipmentStatus.DELIVERED or not self.estimated_delivery:
            return False
        return self.estimated_delivery < timezone.now().date()

    def dwell_times(self):
        """Per stop: (location_name, arrived_at, departed_at, duration_or_None)."""
        events = list(self.events.exclude(location="").order_by("timestamp", "id"))
        stops = []
        for event in events:
            if not stops or stops[-1]["location"] != event.location:
                stops.append({"location": event.location, "arrived_at": event.timestamp})

        results = []
        for i, stop in enumerate(stops):
            arrived_at = stop["arrived_at"]
            if i < len(stops) - 1:
                departed_at = stops[i + 1]["arrived_at"]
                duration = departed_at - arrived_at
            else:
                departed_at = None
                duration = None
            results.append((stop["location"], arrived_at, departed_at, duration))
        return results


class TrackingEvent(models.Model):
    shipment = models.ForeignKey(
        Shipment, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=32, choices=ShipmentStatus.choices)
    # Free-text location name (a hub/facility name typed in, or blank) —
    # not a relation to any other table.
    location = models.CharField(max_length=255, blank=True)
    location_note = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255, blank=True)
    delay_reason = models.CharField(max_length=255, blank=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["-timestamp", "-id"]

    def __str__(self):
        return f"{self.shipment.tracking_number} - {self.event_type} @ {self.timestamp}"

    def save(self, *args, **kwargs):
        if not self.description:
            base = DEFAULT_EVENT_DESCRIPTIONS.get(self.event_type, "")
            if self.location:
                self.description = f"{base} at {self.location}"
            else:
                self.description = base

        with transaction.atomic():
            super().save(*args, **kwargs)
            _recompute_shipment_status(self.shipment_id)


def _recompute_shipment_status(shipment_id):
    shipment = Shipment.objects.select_for_update().get(pk=shipment_id)
    latest = shipment.events.order_by("-timestamp", "-id").first()

    if latest is None:
        shipment.status = ShipmentStatus.LABEL_CREATED
        shipment.current_location = ""
        shipment.delivered_at = None
        shipment.signed_by = ""
        shipment.save(
            update_fields=[
                "status",
                "current_location",
                "delivered_at",
                "signed_by",
            ]
        )
        return

    shipment.status = latest.event_type

    if latest.location:
        shipment.current_location = latest.location
    else:
        last_with_location = (
            shipment.events.exclude(location="")
            .order_by("-timestamp", "-id")
            .first()
        )
        shipment.current_location = (
            last_with_location.location if last_with_location else ""
        )

    if latest.event_type == ShipmentStatus.DELIVERED:
        shipment.delivered_at = latest.timestamp
        if not shipment.signed_by:
            shipment.signed_by = shipment.recipient_name.split(" ")[0]
    else:
        shipment.delivered_at = None
        shipment.signed_by = ""

    shipment.save(
        update_fields=["status", "current_location", "delivered_at", "signed_by"]
    )


@receiver(post_delete, sender=TrackingEvent)
def _on_event_deleted(sender, instance, **kwargs):
    with transaction.atomic():
        _recompute_shipment_status(instance.shipment_id)
