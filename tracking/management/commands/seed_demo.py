import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from faker import Faker

from tracking.models import ServiceLevel, Shipment, ShipmentStatus, TrackingEvent
from tracking.services import create_shipment
from tracking.simulator import (
    DELAY_REASONS,
    SAMPLE_WAYPOINT_NAMES,
    advance,
    run_to_delivery,
)

NIGERIAN_STATES_CITIES = [
    ("Lagos", "Lagos"),
    ("Abuja", "FCT"),
    ("Port Harcourt", "Rivers"),
    ("Kano", "Kano"),
    ("Ibadan", "Oyo"),
    ("Enugu", "Enugu"),
    ("Kaduna", "Kaduna"),
    ("Abeokuta", "Ogun"),
    ("Owerri", "Imo"),
    ("Benin City", "Edo"),
]


class Command(BaseCommand):
    help = "Seed the database with a superuser and sample shipments."

    def add_arguments(self, parser):
        parser.add_argument("--shipments", type=int, default=20)
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args, **options):
        num_shipments = options["shipments"]
        reset = options["reset"]
        fake = Faker("en_NG")

        if reset:
            self.stdout.write("Resetting existing shipments and events...")
            TrackingEvent.objects.all().delete()
            Shipment.objects.all().delete()

        self._seed_superuser()

        with transaction.atomic():
            shipments = [
                self._create_random_shipment(fake) for _ in range(num_shipments)
            ]

        self._simulate_progress(shipments)
        self._print_samples(shipments)

    def _seed_superuser(self):
        User = get_user_model()
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin", email="admin@example.com", password="admin123"
            )
            self.stdout.write(
                self.style.SUCCESS("Created superuser: admin / admin123")
            )
        else:
            self.stdout.write("Superuser 'admin' already exists.")

    def _random_address_fields(self, prefix, fake):
        city, state = random.choice(NIGERIAN_STATES_CITIES)
        return {
            f"{prefix}_name": fake.name(),
            f"{prefix}_phone": f"+234{random.randint(700, 909)}{random.randint(1000000, 9999999)}",
            f"{prefix}_line1": fake.street_address(),
            f"{prefix}_city": city,
            f"{prefix}_state": state,
            f"{prefix}_postal_code": str(random.randint(100000, 109999)),
            f"{prefix}_country": "Nigeria",
        }

    def _create_random_shipment(self, fake):
        origin, destination = random.sample(SAMPLE_WAYPOINT_NAMES, 2)
        service_level = random.choice(ServiceLevel.values)
        created_at = timezone.now() - timedelta(
            days=random.randint(1, 5), hours=random.randint(0, 23)
        )

        fields = {}
        fields.update(self._random_address_fields("sender", fake))
        fields.update(self._random_address_fields("recipient", fake))

        return create_shipment(
            **fields,
            service_level=service_level,
            weight_kg=round(random.uniform(0.5, 25.0), 2),
            dimensions=f"{random.randint(10,60)}x{random.randint(10,60)}x{random.randint(10,60)} cm",
            declared_value=round(random.uniform(2000, 250000), 2),
            origin=origin,
            destination=destination,
            created_at=created_at,
        )

    def _simulate_progress(self, shipments):
        categories = ["untouched", "transit", "out_for_delivery", "delivered"]
        for i, shipment in enumerate(shipments):
            category = categories[i % len(categories)]

            if category == "untouched":
                continue

            if category == "transit":
                max_steps = max(1, len(shipment.route) - 1)
                steps = random.randint(1, max_steps)
                for _ in range(steps):
                    shipment.refresh_from_db()
                    if shipment.status in (
                        ShipmentStatus.OUT_FOR_DELIVERY,
                        ShipmentStatus.DELIVERED,
                    ):
                        break
                    advance(shipment)

            elif category == "out_for_delivery":
                for _ in range(20):
                    shipment.refresh_from_db()
                    if shipment.status in (
                        ShipmentStatus.OUT_FOR_DELIVERY,
                        ShipmentStatus.DELIVERED,
                    ):
                        break
                    advance(shipment)

            elif category == "delivered":
                run_to_delivery(shipment)

        self._ensure_at_least_one_delay(shipments)

    def _ensure_at_least_one_delay(self, shipments):
        has_delay = Shipment.objects.filter(status=ShipmentStatus.DELAYED).exists()
        if has_delay:
            return

        candidate = None
        for shipment in shipments:
            shipment.refresh_from_db()
            if shipment.status not in (
                ShipmentStatus.DELIVERED,
                ShipmentStatus.LABEL_CREATED,
            ):
                candidate = shipment
                break

        if candidate is None:
            return

        latest = candidate.latest_event()
        now = timezone.now()
        new_ts = latest.timestamp + timedelta(hours=random.randint(1, 4))
        if new_ts > now:
            new_ts = now
        TrackingEvent.objects.create(
            shipment=candidate,
            event_type=ShipmentStatus.DELAYED,
            location=latest.location,
            delay_reason=random.choice(DELAY_REASONS),
            timestamp=new_ts,
        )
        self.stdout.write(
            f"Forced a delay on shipment {candidate.tracking_number}."
        )

    def _print_samples(self, shipments):
        def sample_for(status):
            for shipment in shipments:
                shipment.refresh_from_db()
                if shipment.status == status:
                    return shipment.tracking_number
            return None

        in_transit = None
        for shipment in shipments:
            shipment.refresh_from_db()
            if shipment.status in (
                ShipmentStatus.PICKED_UP,
                ShipmentStatus.ARRIVED_AT_FACILITY,
                ShipmentStatus.DEPARTED_FACILITY,
            ):
                in_transit = shipment.tracking_number
                break

        out_for_delivery = sample_for(ShipmentStatus.OUT_FOR_DELIVERY)
        delivered = sample_for(ShipmentStatus.DELIVERED)

        self.stdout.write(self.style.SUCCESS("\nSample tracking numbers:"))
        self.stdout.write(f"  In transit:       {in_transit or 'n/a'}")
        self.stdout.write(f"  Out for delivery: {out_for_delivery or 'n/a'}")
        self.stdout.write(f"  Delivered:        {delivered or 'n/a'}")
