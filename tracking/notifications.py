from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_event_notification_email(event):
    """Email the recipient about a tracking event, if the shipment has an
    address on file and staff haven't muted notifications for it."""
    # Local import: models.py imports this module at load time, so a
    # top-level import here would be circular.
    from .models import ShipmentStatus

    shipment = event.shipment
    if not shipment.email_notifications_enabled or not shipment.recipient_email:
        return

    first_name = shipment.recipient_name.split(" ")[0]
    status_label = event.get_event_type_display()
    subject = f"Shipment {shipment.tracking_number}: {status_label}"

    delivered_at = event.timestamp if event.event_type == ShipmentStatus.DELIVERED else None
    eta = shipment.estimated_delivery if not delivered_at else None

    context = {
        "subject": subject,
        "first_name": first_name,
        "status_label": status_label,
        "shipment": shipment,
        "event": event,
        "delivered_at": delivered_at,
        "eta": eta,
    }

    text_lines = [
        f"Hi {first_name},",
        "",
        f"Your shipment {shipment.tracking_number} is now: {status_label}.",
    ]
    if event.location:
        text_lines.append(f"Location: {event.location}")
    if event.delay_reason:
        text_lines.append(f"Reason: {event.delay_reason}")
    if delivered_at:
        text_lines.append(f"Delivered: {delivered_at}")
    elif eta:
        text_lines.append(f"Estimated delivery: {eta}")
    text_lines += ["", "- Bureau Private Delivery Company"]

    html_body = render_to_string("tracking/email/shipment_update.html", context)

    message = EmailMultiAlternatives(
        subject,
        "\n".join(text_lines),
        settings.DEFAULT_FROM_EMAIL,
        [shipment.recipient_email],
        reply_to=[settings.DEFAULT_FROM_EMAIL],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=True)
