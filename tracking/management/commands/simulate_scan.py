from django.core.management.base import BaseCommand, CommandError

from tracking.models import Shipment
from tracking.simulator import advance, advance_all


class Command(BaseCommand):
    help = "Advance a shipment (or all shipments) by simulating scans. Runs once and exits."

    def add_arguments(self, parser):
        parser.add_argument("tracking_number", nargs="?", default=None)
        parser.add_argument("--steps", type=int, default=1)
        parser.add_argument("--all", action="store_true")

    def handle(self, *args, **options):
        if options["all"]:
            count = advance_all()
            self.stdout.write(self.style.SUCCESS(f"Advanced {count} shipment(s)."))
            return

        tracking_number = options["tracking_number"]
        if not tracking_number:
            raise CommandError(
                "Provide a tracking_number, or use --all to advance every shipment."
            )

        try:
            shipment = Shipment.objects.get(tracking_number=tracking_number)
        except Shipment.DoesNotExist as exc:
            raise CommandError(
                f"No shipment found with tracking number '{tracking_number}'."
            ) from exc

        steps_done = 0
        for _ in range(options["steps"]):
            event = advance(shipment)
            if event is None:
                break
            steps_done += 1

        shipment.refresh_from_db()
        self.stdout.write(
            self.style.SUCCESS(
                f"Advanced {shipment.tracking_number} by {steps_done} step(s). "
                f"Status is now {shipment.get_status_display()}."
            )
        )
