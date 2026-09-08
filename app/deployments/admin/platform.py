"""The Platform admin and its inlines/filter."""

from datetime import datetime, timedelta

from django.contrib.admin import BooleanFieldListFilter
from django.contrib.gis import admin
from django.http.request import HttpRequest
from django_object_actions import DjangoObjectActions, action

from ..models import Alert, Platform, PlatformLink, ProgramAttribution, TimeSeries
from ..tasks import refresh
from ..widgets import EsriOceanBasemapWidget
from .displays import timeseries_status
from .system_messages import (
    SystemMessageListFilter,
    SystemMessageSidebarMixin,
    system_message_status,
)
from .timeseries import TimeSeriesInline


class ProgramAttributionInline(admin.TabularInline):
    model = ProgramAttribution
    extra = 0


class AlertInline(admin.TabularInline):
    model = Alert
    extra = 0


class PlatformLinkInline(admin.TabularInline):
    model = PlatformLink
    extra = 0


class TimeseriesActiveFilter(BooleanFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path) -> None:  # noqa: PLR0913
        super().__init__(field, request, params, model, model_admin, field_path)

        self.title = "Timeseries Active"


@admin.register(Platform)
class PlatformAdmin(SystemMessageSidebarMixin, DjangoObjectActions, admin.GISModelAdmin):
    ordering = ["name", "mooring_site_desc", "ndbc_site_id"]
    inlines = [
        AlertInline,
        TimeSeriesInline,
        ProgramAttributionInline,
        PlatformLinkInline,
    ]

    actions = [
        "disable_old_timeseries",
        "remove_end_time",
        "disable_timeseries",
        "enable_timeseries",
        "refresh_timeseries",
    ]
    search_fields = [
        "name",
        "mooring_site_desc",
        "ndbc_site_id",
        "alerts__message",
        "timeseries__variable",
        "timeseries__dataset__name",
        "timeseries__dataset__server__name",
        "timeseries__data_type__standard_name",
        "timeseries__data_type__short_name",
        "timeseries__data_type__long_name",
        "timeseries__data_type__units",
    ]

    list_display = [
        "name",
        "platform_type",
        timeseries_status,
        system_message_status,
        "mooring_site_desc",
        "ndbc_site_id",
    ]
    list_filter = [
        SystemMessageListFilter,
        "platform_type",
        "timeseries__dataset__server__name",
        ("timeseries__active", TimeseriesActiveFilter),
        "timeseries__data_type__standard_name",
        "timeseries__dataset__name",
    ]

    change_actions = ["refresh_platform_datasets"]

    gis_widget = EsriOceanBasemapWidget
    gis_widget_kwargs = {
        "attrs": {
            "default_zoom": 6.5,
            "default_lon": -70.0,
            "default_lat": 43.0,
        },
    }

    def get_queryset(self, request: HttpRequest):
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related(
            "timeseries_set",
            "timeseries_set__data_type",
            # The badge gathers messages from each platform's datasets and servers, and from
            # the platform itself; without these the changelist would go N+1 over the page.
            "timeseries_set__dataset__server",
            "system_messages",
        )
        return queryset

    @action(description="Refresh all datasets for this platform")
    def refresh_platform_datasets(self, request, obj):
        datasets_to_queue = set()
        for ts in obj.timeseries_set.all():
            datasets_to_queue.add(ts.dataset_id)

        for dataset_id in datasets_to_queue:
            refresh.refresh_dataset.delay(dataset_id)

        self.message_user(
            request,
            f"Queued {len(datasets_to_queue)} datasets for refresh.",
        )

    @admin.action(description="Disable timeseries that are more than a week out of date")
    def disable_old_timeseries(self, request, queryset):
        platforms_ids = [platform.id for platform in queryset.iterator(chunk_size=100)]
        timeseries_to_update = []

        week_ago = datetime.now() - timedelta(days=7)

        ts_week_ago = TimeSeries.objects.filter(
            value_time__lt=week_ago,
            active=True,
            platform_id__in=platforms_ids,
        )

        for ts in ts_week_ago.iterator(chunk_size=100):
            ts.active = False
            timeseries_to_update.append(ts)

        TimeSeries.objects.bulk_update(timeseries_to_update, ["active"])

        self.message_user(
            request,
            f"Disabled {len(timeseries_to_update)} that all were updated longer than a week ago "
            f"from {len(platforms_ids)} platforms.",
        )

    @admin.action(description="Refresh timeseries datasets")
    def refresh_timeseries(self, request, queryset):
        datasets_to_queue = set()

        for platform in queryset.iterator(chunk_size=100):
            for ts in platform.timeseries_set.all():
                datasets_to_queue.add(ts.dataset_id)

        for dataset_id in datasets_to_queue:
            refresh.refresh_dataset.delay(dataset_id)

        self.message_user(
            request,
            f"{len(datasets_to_queue)} datasets queued to be refreshed.",
        )

    @admin.action(
        description="Remove end time for timeseries",
    )
    def remove_end_time(self, request, queryset):
        platforms = []
        timeseries = []

        for platform in queryset.iterator(chunk_size=100):
            platforms.append(platform)
            for ts in platform.timeseries_set.filter(end_time__isnull=False):
                ts.end_time = None
                timeseries.append(ts)

        if timeseries:
            TimeSeries.objects.bulk_update(timeseries, ["end_time"])

        self.message_user(
            request,
            (
                f"Removed end time for {len(timeseries)} timeseries with an end time from "
                f"{len(platforms)} platform"
            ),
        )

    @admin.action(description="Disable updating of timeseries")
    def disable_timeseries(self, request, queryset):
        platforms = []
        timeseries = []

        for platform in queryset.iterator(chunk_size=100):
            platforms.append(platform)
            for ts in platform.timeseries_set.all():
                ts.active = False
                timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ["active"])

        self.message_user(
            request,
            f"Disabled {len(timeseries)} timeseries from {len(platforms)} platforms",
        )

    @admin.action(description="Enable updating of timeseries")
    def enable_timeseries(self, request, queryset):
        platforms = []
        timeseries = []

        for platform in queryset.iterator(chunk_size=100):
            platforms.append(platform)
            for ts in platform.timeseries_set.all():
                ts.active = True
                timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ["active"])

        self.message_user(
            request,
            f"Enable {len(timeseries)} timeseries from {len(platforms)} platforms",
        )
