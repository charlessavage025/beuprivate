from django import forms

from .models import ServiceLevel


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
