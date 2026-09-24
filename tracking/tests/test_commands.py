from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from tracking.models import ShipmentStatus
from .factories import make_shipment


@override_settings(SIM_DELAY_RATE=0)
class SimulateScanCommandTests(TestCase):
    def setUp(self):
        self.shipment = make_shipment(origin="Origin Hub", destination="Destination Hub")

    def test_advances_shipment_by_n_steps(self):
        out = StringIO()
        call_command(
            "simulate_scan", self.shipment.tracking_number, "--steps", "2", stdout=out
        )
        self.shipment.refresh_from_db()
        # Started at LABEL_CREATED: two steps -> PICKED_UP -> ARRIVED_AT_FACILITY
        self.assertEqual(self.shipment.status, ShipmentStatus.ARRIVED_AT_FACILITY)
        self.assertIn("Advanced", out.getvalue())

    def test_all_flag_advances_every_shipment(self):
        out = StringIO()
        call_command("simulate_scan", "--all", stdout=out)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, ShipmentStatus.PICKED_UP)
