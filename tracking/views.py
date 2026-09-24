from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import ScanForm, ShipmentCreateForm
from .models import Shipment, ShipmentStatus, TrackingEvent
from .services import create_shipment
from .simulator import advance, advance_all, flag_delay, rewind, run_to_delivery


def staff_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied("Staff access required.")
        return view_func(request, *args, **kwargs)

    return wrapper


def build_track_context(shipment):
    return {
        "shipment": shipment,
        "is_delayed": shipment.status == ShipmentStatus.DELAYED,
        "events": shipment.events.all(),
        "is_delivered": shipment.status == ShipmentStatus.DELIVERED,
    }


def index(request):
    return render(request, "tracking/index.html", {})


def track_search(request):
    tracking_number = request.GET.get("tracking_number", "").strip()
    shipment = Shipment.objects.filter(tracking_number=tracking_number).first()

    if not shipment:
        if request.htmx:
            return render(
                request,
                "tracking/partials/not_found.html",
                {"tracking_number": tracking_number},
            )
        return render(
            request,
            "tracking/index.html",
            {"error": f"No shipment found for tracking number '{tracking_number}'."},
        )

    if request.htmx:
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse(
            "track_detail", args=[shipment.tracking_number]
        )
        return response

    return redirect("track_detail", tracking_number=shipment.tracking_number)


def track_detail(request, tracking_number):
    shipment = get_object_or_404(Shipment, tracking_number=tracking_number)
    context = build_track_context(shipment)
    if request.htmx:
        return render(request, "tracking/partials/track_detail_content.html", context)
    return render(request, "tracking/track_detail.html", context)


def track_timeline(request, tracking_number):
    shipment = get_object_or_404(Shipment, tracking_number=tracking_number)
    return render(
        request, "tracking/partials/timeline.html", build_track_context(shipment)
    )


def _dashboard_context(request, status):
    shipments = Shipment.objects.order_by("-created_at")
    if status:
        shipments = shipments.filter(status=status)

    counts_qs = Shipment.objects.values("status").annotate(count=Count("id"))
    counts_map = {row["status"]: row["count"] for row in counts_qs}

    return {
        "shipments": shipments,
        "counts_map": counts_map,
        "status_choices": ShipmentStatus.choices,
        "selected_status": status,
        "total_count": Shipment.objects.count(),
    }


@staff_required
def staff_dashboard(request):
    status = request.GET.get("status", "")
    context = _dashboard_context(request, status)
    if request.htmx:
        return render(request, "tracking/partials/shipments_table.html", context)
    return render(request, "tracking/staff_dashboard.html", context)


@staff_required
@require_POST
def staff_advance_row(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk)
    advance(shipment)
    shipment.refresh_from_db()
    return render(request, "tracking/partials/shipment_row.html", {"shipment": shipment})


@staff_required
@require_POST
def staff_run_to_delivery(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk)
    run_to_delivery(shipment)
    return render(request, "tracking/partials/shipment_row.html", {"shipment": shipment})


@staff_required
@require_POST
def staff_rewind_row(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk)
    rewind(shipment)
    shipment.refresh_from_db()
    return render(request, "tracking/partials/shipment_row.html", {"shipment": shipment})


@staff_required
@require_POST
def staff_flag_delay_row(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk)
    reason = request.htmx.prompt or ""
    flag_delay(shipment, reason=reason)
    shipment.refresh_from_db()
    return render(request, "tracking/partials/shipment_row.html", {"shipment": shipment})


@staff_required
@require_POST
def staff_advance_all(request):
    advance_all()
    status = request.GET.get("status", "")
    context = _dashboard_context(request, status)
    return render(request, "tracking/partials/dashboard_content.html", context)


@staff_required
def staff_shipment_new(request):
    if request.method == "POST":
        form = ShipmentCreateForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            shipment = create_shipment(
                sender_name=data["sender_name"],
                sender_phone=data["sender_phone"],
                sender_line1=data["sender_line1"],
                sender_line2=data["sender_line2"],
                sender_city=data["sender_city"],
                sender_state=data["sender_state"],
                sender_postal_code=data["sender_postal_code"],
                sender_country=data["sender_country"],
                recipient_name=data["recipient_name"],
                recipient_phone=data["recipient_phone"],
                recipient_line1=data["recipient_line1"],
                recipient_line2=data["recipient_line2"],
                recipient_city=data["recipient_city"],
                recipient_state=data["recipient_state"],
                recipient_postal_code=data["recipient_postal_code"],
                recipient_country=data["recipient_country"],
                service_level=data["service_level"],
                weight_kg=data["weight_kg"],
                dimensions=data["dimensions"],
                declared_value=data["declared_value"],
                origin=data["origin"],
                destination=data["destination"],
                stops=form.route_stops(),
                created_by=request.user,
            )
            return redirect("track_detail", tracking_number=shipment.tracking_number)
    else:
        form = ShipmentCreateForm()
    return render(request, "tracking/staff_shipment_new.html", {"form": form})


@staff_required
def staff_scan(request):
    success = False
    if request.method == "POST":
        form = ScanForm(request.POST)
        if form.is_valid():
            shipment = Shipment.objects.get(
                tracking_number=form.cleaned_data["tracking_number"]
            )
            kwargs = {
                "shipment": shipment,
                "event_type": form.cleaned_data["event_type"],
                "location": form.cleaned_data["location"],
                "location_note": form.cleaned_data["location_note"],
                "delay_reason": form.cleaned_data["delay_reason"],
                "created_by": request.user,
            }
            if form.cleaned_data.get("timestamp"):
                kwargs["timestamp"] = form.cleaned_data["timestamp"]
            event = TrackingEvent.objects.create(**kwargs)

            signed_by = form.cleaned_data.get("signed_by")
            if event.event_type == ShipmentStatus.DELIVERED and signed_by:
                Shipment.objects.filter(pk=shipment.pk).update(signed_by=signed_by)

            success = True
            form = ScanForm()
    else:
        form = ScanForm()

    context = {"form": form, "success": success}
    if request.htmx:
        return render(request, "tracking/partials/scan_form.html", context)
    return render(request, "tracking/staff_scan.html", context)
