from datetime import datetime, timedelta
from typing import Any

from django.contrib.admin import BooleanFieldListFilter, SimpleListFilter
from django.contrib.gis import admin
from django.db.models.query import QuerySet
from django.http.request import HttpRequest
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    Alert,
    BufferType,
    DataType,
    ErddapDataset,
    ErddapServer,
    FloodLevel,
    MooringType,
    Platform,
    PlatformLink,
    Program,
    ProgramAttribution,
    StationType,
    TimeSeries,
)
from .tasks import refresh


class FloodLevelInline(admin.StackedInline):
    model = FloodLevel
    extra = 0


class TimesiersStatusListFilter(SimpleListFilter):
    title = "Timeseries status"
    parameter_name = "timeseries_status"

    def lookups(self, request: Any, model_admin: Any) -> list[tuple[Any, str]]:
        return [
            ("last_hour", "Within the last hour"),
            ("last_day", "Within the last day"),
            ("more_than_day", "More than a day ago"),
            ("never", "Never"),
        ]

    def queryset(self, request: Any, queryset: QuerySet[Any]) -> QuerySet[Any] | None:
        if self.value() == "last_hour":
            return queryset.filter(value_time__gte=timezone.now() - timedelta(hours=1))
        elif self.value() == "last_day":
            return queryset.filter(
                value_time__gte=timezone.now() - timedelta(days=1),
                value_time__lt=timezone.now() - timedelta(hours=1),
            )
        elif self.value() == "more_than_day":
            return queryset.filter(value_time__lt=timezone.now() - timedelta(days=1))
        elif self.value() == "never":
            return queryset.filter(value_time__isnull=True)
        else:
            return queryset


@admin.register(TimeSeries)
class TimeSeriesAdmin(admin.ModelAdmin):
    model = TimeSeries
    inlines = [FloodLevelInline]

    autocomplete_fields = ["dataset", "data_type", "buffer_type"]
    readonly_fields = ["test_timeseries"]

    actions = ["refresh_timeseries"]

    list_display = ["platform", "value", "timeseries_status", "data_type"]
    list_filter = [TimesiersStatusListFilter, "active", "platform", "data_type"]
    search_fields = [
        "platform__name",
        "data_type__standard_name",
        "data_type__short_name",
        "data_type__long_name",
        "data_type__units",
    ]

    @admin.display(description="Timeseries status")
    def timeseries_status(self, instance: TimeSeries):
        now = timezone.now()
        hour_ago = now - timedelta(hours=24)
        day_ago = now - timedelta(days=1)

        if instance.value_time is None:
            return format_html("<span style='color: gray;'>No data</span>")
        if instance.value_time < day_ago:
            return format_html("<span style='color: red;'>{}</span>", instance.value_time)
        if instance.value_time < hour_ago:
            return format_html("<span style='color: yellow;'>{}</span>", instance.value_time)
        return format_html("<span style='color: green;'>{}</span>", instance.value_time)

    @admin.display(
        description="Test if a timeseries is formatted correctly to connect to ERDDAP",
    )
    def test_timeseries(self, instance):
        dataset_url = instance.dataset_url("htmlTable")

        return mark_safe(f"<a href='{dataset_url}'>Test ERDDAP Timeseries</a>")  # nosec

    @admin.action(description="Refresh datasets for selected timeseries")
    def refresh_timeseries(self, request, queryset):
        datasets_to_queue = set()

        for ts in queryset.iterator(chunk_size=100):
            datasets_to_queue.add(ts.dataset.id)

        for dataset_id in datasets_to_queue:
            refresh.refresh_dataset.delay(dataset_id)

        self.message_user(
            request,
            f"Queued {len(datasets_to_queue)} datasets for refresh.",
        )

    def get_queryset(self, request: HttpRequest):
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related("data_type", "platform")
        return queryset


class TimeSeriesInline(admin.StackedInline):
    model = TimeSeries
    extra = 0

    autocomplete_fields = ["platform", "dataset", "data_type", "buffer_type"]
    readonly_fields = ["test_timeseries"]

    show_change_link = True

    fieldsets = [
        (
            None,
            {
                "fields": [
                    ("dataset", "platform", "variable"),
                    ("data_type", "active"),
                    ("value_time", "end_time"),
                    ("value", "test_timeseries"),
                ],
            },
        ),
        (
            "Advanced",
            {
                "classes": ["collapse"],
                "fields": [
                    ("constraints", "depth"),
                    ("timeseries_type", "extrema", "buffer_type"),
                    ("datum_mhhw_meters", "datum_mhw_meters"),
                    ("datum_mtl_meters", "datum_msl_meters"),
                    ("datum_mlw_meters", "datum_mllw_meters"),
                ],
            },
        ),
    ]

    @admin.display(
        description="Test if a timeseries is formatted correctly to connect to ERDDAP",
    )
    def test_timeseries(self, instance):
        dataset_url = instance.dataset_url("htmlTable")

        return mark_safe(f"<a href='{dataset_url}'>Test ERDDAP Timeseries</a>")  # nosec


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


@admin.display(description="Timeseries status")
def timeseries_status(obj: ErddapDataset | Platform):
    """Shows an inline display of timeseries status on a dataset or platform admin"""
    now = timezone.now()
    hour_ago = now - timedelta(hours=24)
    day_ago = now - timedelta(days=1)

    active_timeseries = []
    inactive_timeseries = []

    for ts in obj.timeseries_set.all():
        if ts.active and ts.value_time is not None:
            try:
                if ts.end_time < now:
                    inactive_timeseries.append(ts)
                    continue
            except TypeError:
                pass
            active_timeseries.append(ts)
        else:
            inactive_timeseries.append(ts)

    hour_delayed = [ts for ts in active_timeseries if ts.value_time < hour_ago]
    day_delayed = [ts for ts in active_timeseries if ts.value_time < day_ago]

    inactive_color = "gray" if len(inactive_timeseries) == 0 else "black"

    active_title = "\n".join(
        f"{ts} ({ts.value} @ {ts.value_time:%Y-%m-%d %H:%M})"
        if ts.value_time
        else f"{ts} (Not refreshed)"
        for ts in active_timeseries
    )
    inactive_title = "\n".join(
        f"{ts} ({ts.value} @ {ts.value_time:%Y-%m-%d %H:%M})"
        if ts.value_time
        else f"{ts} (Not refreshed)"
        for ts in inactive_timeseries
    )

    if len(day_delayed) > 0:
        return format_html(
            (
                "<span style='color: {};' title='{}'>{}</span>"
                " {} / {} "
                "<span style='color: {};' title='{}'>({} inactive)</span>"
            ),
            "red",
            active_title,
            "Delayed by at least a day",
            len(day_delayed),
            len(active_timeseries),
            inactive_color,
            inactive_title,
            len(inactive_timeseries),
        )
    elif len(hour_delayed) > 0:
        return format_html(
            (
                "<span style='color: {};' title='{}'>"
                "{} / {} "
                "<span style='color: {};' title='{}'>({} inactive)</span>"
            ),
            "yellow",
            active_title,
            "Delayed by at least an hour",
            len(hour_delayed),
            len(active_timeseries),
            inactive_color,
            inactive_title,
            len(inactive_timeseries),
        )

    return format_html(
        (
            "<span style='color: {};' title='{}'>{}</span>"
            " {} / {} "
            "<span style='color: {};' title='{}'>({} inactive)</span>"
        ),
        "green",
        active_title,
        "Active",
        len(active_timeseries),
        len(active_timeseries),
        inactive_color,
        inactive_title,
        len(inactive_timeseries),
    )


@admin.register(Platform)
class PlatformAdmin(admin.GISModelAdmin):
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

    list_display = ["name", "platform_type", timeseries_status, "mooring_site_desc", "ndbc_site_id"]
    list_filter = [
        "platform_type",
        "timeseries__dataset__server__name",
        ("timeseries__active", TimeseriesActiveFilter),
        "timeseries__data_type__standard_name",
        "timeseries__dataset__name",
    ]

    def get_queryset(self, request: HttpRequest):
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related("timeseries_set", "timeseries_set__data_type")
        return queryset

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


@admin.register(ErddapServer)
class ErddapServerAdmin(admin.ModelAdmin):
    ordering = ["name"]

    actions = ["disable_timeseries", "enable_timeseries", "refresh_server"]

    @admin.action(description="Refresh timeseries for servers")
    def refresh_server(self, request, queryset):
        queued_servers = []

        for server in queryset.iterator(chunk_size=100):
            refresh.refresh_server.delay(server.id, healthcheck=False)
            queued_servers.append(server)

        self.message_user(
            request,
            f"Queued timeseries from {len(queued_servers)} server to be refreshed",
        )

    @admin.action(description="Disable updating of timeseries")
    def disable_timeseries(self, request, queryset):
        datasets = []
        timeseries = []

        for server in queryset.iterator(chunk_size=100):
            for dataset in server.erddapdataset_set.all():
                datasets.append(dataset)
                for ts in dataset.timeseries_set.all():
                    ts.active = False
                    timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ["active"])

        self.message_user(
            request,
            f"Disabled {len(timeseries)} timeseries from {len(datasets)} datasets",
        )

    @admin.action(description="Enable updating of timeseries")
    def enable_timeseries(self, request, queryset):
        datasets = []
        timeseries = []

        for server in queryset.iterator(chunk_size=100):
            for dataset in server.erddapdataset_set.all():
                datasets.append(dataset)
                for ts in dataset.timeseries_set.all():
                    ts.active = True
                    timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ["active"])

        self.message_user(
            request,
            f"Disabled {len(timeseries)} timeseries from {len(datasets)} datasets",
        )


class RefreshStatusListFilter(SimpleListFilter):
    title = "Refresh status"
    parameter_name = "refresh_status"

    def lookups(self, request: Any, model_admin: Any) -> list[tuple[Any, str]]:
        return [
            ("last_hour", "Within the last hour"),
            ("last_day", "Within the last day"),
            ("more_than_day", "More than a day ago"),
            ("never", "Never"),
        ]

    def queryset(self, request: Any, queryset: QuerySet[Any]) -> QuerySet[Any] | None:
        if self.value() == "last_hour":
            return queryset.filter(refresh_attempted__gte=timezone.now() - timedelta(hours=1))
        elif self.value() == "last_day":
            return queryset.filter(
                refresh_attempted__gte=timezone.now() - timedelta(days=1),
                refresh_attempted__lt=timezone.now() - timedelta(hours=1),
            )
        elif self.value() == "more_than_day":
            return queryset.filter(refresh_attempted__lt=timezone.now() - timedelta(days=1))
        elif self.value() == "never":
            return queryset.filter(refresh_attempted__isnull=True)
        else:
            return queryset


@admin.register(ErddapDataset)
class ErddapDatasetAdmin(admin.ModelAdmin):
    ordering = ["name"]
    search_fields = ["name", "server__name", "server__base_url"]
    list_display = [
        "name",
        timeseries_status,
        "server",
        "refresh_status",
    ]
    list_filter = ["server__name", RefreshStatusListFilter]
    inlines = [TimeSeriesInline]

    actions = ["disable_timeseries", "enable_timeseries", "refresh_dataset"]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related(
            "timeseries_set",
            "timeseries_set__data_type",
            "timeseries_set__platform",
        )
        return queryset

    @admin.display(description="Refresh attempted")
    def refresh_status(self, obj: ErddapDataset):
        now = timezone.now()
        hour_ago = now - timedelta(hours=24)
        day_ago = now - timedelta(days=1)

        last_refreshed = f"Last refreshed at: {obj.refresh_attempted:%Y-%m-%d %H:%M}"

        if obj.refresh_attempted is None:
            return format_html(
                "<span style='color: {};'>{}</span>",
                "gray",
                "Never refreshed",
            )
        if obj.refresh_attempted < day_ago:
            return format_html(
                "<span style='color: {};' title='{}'>{}</span>",
                "red",
                last_refreshed,
                "More than 24 hours ago",
            )
        elif obj.refresh_attempted < hour_ago:
            return format_html(
                "<span style='color: {};' title='{}'>{}</span>",
                "yellow",
                last_refreshed,
                "More than 1 hour ago",
            )
        else:
            return format_html(
                "<span style='color: {};' title='{}'>{}</span>",
                "green",
                last_refreshed,
                "Less than 1 hour ago",
            )

    @admin.action(description="Refresh timeseries associated with datasets")
    def refresh_dataset(self, request, queryset):
        queued_datasets = []

        for dataset in queryset.iterator(chunk_size=100):
            refresh.refresh_dataset.delay(dataset.id, healthcheck=False)
            queued_datasets.append(dataset)

        self.message_user(
            request,
            f"Queued timeseries to be refreshed from {len(queued_datasets)} datasets",
        )

    @admin.action(description="Disable updating of timeseries")
    def disable_timeseries(self, request, queryset):
        datasets = []
        timeseries = []

        for dataset in queryset.iterator(chunk_size=100):
            datasets.append(dataset)
            for ts in dataset.timeseries_set.all():
                ts.active = False
                timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ["active"])

        self.message_user(
            request,
            f"Disabled {len(timeseries)} timeseries from {len(datasets)} datasets",
        )

    @admin.action(description="Enable updating of timeseries")
    def enable_timeseries(self, request, queryset):
        datasets = []
        timeseries = []

        for dataset in queryset.iterator(chunk_size=100):
            datasets.append(dataset)
            for ts in dataset.timeseries_set.all():
                ts.active = True
                timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ["active"])

        self.message_user(
            request,
            f"Disabled {len(timeseries)} timeseries from {len(datasets)} datasets",
        )


@admin.register(DataType)
class DataTypeAdmin(admin.ModelAdmin):
    search_fields = ["short_name", "standard_name", "long_name", "units"]


@admin.register(BufferType)
class BufferTypeAdmin(admin.ModelAdmin):
    search_fields = ["name"]


admin.site.register(Program)
admin.site.register(MooringType)
admin.site.register(StationType)
