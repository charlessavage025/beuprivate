from django.contrib import admin

from .models import Shipment, TrackingEvent


class TrackingEventInline(admin.TabularInline):
    model = TrackingEvent
    extra = 0
    fields = (
        "event_type",
        "location",
        "location_note",
        "description",
        "delay_reason",
        "timestamp",
        "created_by",
    )
    ordering = ("-timestamp",)


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        "tracking_number",
        "status",
        "current_location",
        "service_level",
        "created_at",
    )
    list_filter = ("status", "service_level")
    search_fields = ("tracking_number",)
    inlines = [TrackingEventInline]


@admin.register(TrackingEvent)
class TrackingEventAdmin(admin.ModelAdmin):
    list_display = ("shipment", "event_type", "location", "timestamp", "created_by")
    list_filter = ("event_type",)
    search_fields = ("shipment__tracking_number",)
