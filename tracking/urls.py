from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("track/", views.track_search, name="track_search"),
    path("track/<str:tracking_number>/", views.track_detail, name="track_detail"),
    path(
        "track/<str:tracking_number>/timeline/",
        views.track_timeline,
        name="track_timeline",
    ),
    path("staff/", views.staff_dashboard, name="staff_dashboard"),
    path(
        "staff/shipments/new/",
        views.staff_shipment_new,
        name="staff_shipment_new",
    ),
    path(
        "staff/shipments/<int:pk>/advance/",
        views.staff_advance_row,
        name="staff_advance_row",
    ),
    path(
        "staff/shipments/<int:pk>/run-to-delivery/",
        views.staff_run_to_delivery,
        name="staff_run_to_delivery",
    ),
    path(
        "staff/shipments/<int:pk>/rewind/",
        views.staff_rewind_row,
        name="staff_rewind_row",
    ),
    path(
        "staff/shipments/<int:pk>/flag-delay/",
        views.staff_flag_delay_row,
        name="staff_flag_delay_row",
    ),
    path(
        "staff/shipments/<int:pk>/toggle-email/",
        views.staff_toggle_email_row,
        name="staff_toggle_email_row",
    ),
    path(
        "staff/shipments/<int:pk>/delete/",
        views.staff_delete_shipment_row,
        name="staff_delete_shipment_row",
    ),
    path("staff/advance-all/", views.staff_advance_all, name="staff_advance_all"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="tracking/login.html"),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "accounts/password-change/",
        auth_views.PasswordChangeView.as_view(
            template_name="tracking/password_change.html"
        ),
        name="password_change",
    ),
    path(
        "accounts/password-change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="tracking/password_change_done.html"
        ),
        name="password_change_done",
    ),
]
