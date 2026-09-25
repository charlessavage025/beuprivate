from django import forms

from .models import ServiceLevel, Shipment, ShipmentStatus


class ShipmentCreateForm(forms.Form):
    sender_name = forms.CharField(max_length=255, label="Sender name")
    sender_phone = forms.CharField(max_length=32, label="Sender phone")
    sender_line1 = forms.CharField(max_length=255, label="Sender address")
    sender_line2 = forms.CharField(max_length=255, required=False)
    sender_city = forms.CharField(max_length=128)
    sender_state = forms.CharField(max_length=128)
    sender_postal_code = forms.CharField(max_length=32, required=False)
    sender_country = forms.CharField(max_length=128, initial="Nigeria")

    recipient_name = forms.CharField(max_length=255, label="Recipient name")
    recipient_phone = forms.CharField(max_length=32, label="Recipient phone")
    recipient_email = forms.EmailField(label="Recipient email")
    recipient_line1 = forms.CharField(max_length=255, label="Recipient address")
    recipient_line2 = forms.CharField(max_length=255, required=False)
    recipient_city = forms.CharField(max_length=128)
    recipient_state = forms.CharField(max_length=128)
    recipient_postal_code = forms.CharField(max_length=32, required=False)
    recipient_country = forms.CharField(max_length=128, initial="Nigeria")

    service_level = forms.ChoiceField(choices=ServiceLevel.choices)
    weight_kg = forms.DecimalField(max_digits=8, decimal_places=2, min_value=0.01)
    dimensions = forms.CharField(max_length=64, required=False)
    declared_value = forms.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )

    origin = forms.CharField(
        max_length=255, label="Origin (hub/facility name)"
    )
    destination = forms.CharField(
        max_length=255, label="Destination (hub/facility name)"
    )
    stops = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label="Stops in between (optional, one hub/facility per line, in order)",
        help_text="This is the exact route the shipment will move through — "
        "type in as many or as few stops as you like, one per line.",
    )

    def clean(self):
        cleaned = super().clean()
        origin = (cleaned.get("origin") or "").strip()
        destination = (cleaned.get("destination") or "").strip()
        cleaned["origin"] = origin
        cleaned["destination"] = destination

        if origin and destination and origin.lower() == destination.lower():
            raise forms.ValidationError(
                "Origin and destination must be different."
            )

        stops = [
            line.strip()
            for line in (cleaned.get("stops") or "").splitlines()
            if line.strip()
        ]
        seen = {origin.lower(), destination.lower()} - {""}
        for stop in stops:
            if stop.lower() in seen:
                raise forms.ValidationError(
                    f"'{stop}' is used more than once in the route. "
                    "Each stop must be different."
                )
            seen.add(stop.lower())

        cleaned["route_stops"] = stops
        return cleaned

    def route_stops(self):
        return self.cleaned_data.get("route_stops", [])


class ScanForm(forms.Form):
    tracking_number = forms.CharField(max_length=12)
    event_type = forms.ChoiceField(choices=ShipmentStatus.choices)
    location = forms.CharField(
        max_length=255, required=False, label="Location / facility name"
    )
    location_note = forms.CharField(max_length=255, required=False)
    delay_reason = forms.CharField(
        max_length=255, required=False, label="Delay reason"
    )
    signed_by = forms.CharField(
        max_length=255,
        required=False,
        label="Signed by (if delivered in person)",
        help_text="Who actually took the package, e.g. a neighbor or security "
        "desk. Leave blank to assume the named recipient signed for it.",
    )
    timestamp = forms.DateTimeField(required=False)

    def clean_tracking_number(self):
        tracking_number = self.cleaned_data["tracking_number"].strip()
        if not Shipment.objects.filter(tracking_number=tracking_number).exists():
            raise forms.ValidationError("No shipment with that tracking number.")
        return tracking_number

    def clean(self):
        cleaned = super().clean()
        event_type = cleaned.get("event_type")
        location = (cleaned.get("location") or "").strip()
        cleaned["location"] = location
        if event_type in (
            ShipmentStatus.ARRIVED_AT_FACILITY,
            ShipmentStatus.DEPARTED_FACILITY,
        ) and not location:
            raise forms.ValidationError(
                "A location/facility name is required for arrival/departure scans."
            )

        if event_type == ShipmentStatus.DELAYED and not (cleaned.get("delay_reason") or "").strip():
            raise forms.ValidationError(
                "A reason is required when marking a shipment as delayed."
            )

        tracking_number = cleaned.get("tracking_number")
        if tracking_number:
            shipment = Shipment.objects.filter(
                tracking_number=tracking_number
            ).first()
            if shipment and shipment.status == ShipmentStatus.DELIVERED:
                raise forms.ValidationError(
                    "This shipment has already been delivered."
                )
        return cleaned
