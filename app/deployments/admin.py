from datetime import timedelta

from django.contrib.admin import BooleanFieldListFilter
from django.contrib.gis import admin
from django.utils import timezone
from django.utils.safestring import mark_safe

from .models import (
    Alert,
    BufferType,
    DataType,
    ErddapDataset,
    ErddapServer,
    MooringType,
    Platform,
    Program,
    ProgramAttribution,
    StationType,
    TimeSeries,
)


class TimeSeriesInline(admin.StackedInline):
    model = TimeSeries
    extra = 0

    autocomplete_fields = ["dataset", "data_type", "buffer_type"]
    readonly_fields = ["test_timeseries"]

    fieldsets = [
        (
            None,
            {
                "fields": [
                    ("dataset", "variable", "data_type", "depth"),
                    ("value_time", "constraints"),
                    ("value", "active"),
                ],
            },
        ),
        (
            "Advanced",
            {
                "classes": ["collapse"],
                "fields": [
                    ("start_time", "end_time"),
                    ("test_timeseries", "buffer_type"),
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


class TimeseriesActiveFilter(BooleanFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path) -> None:
        super().__init__(field, request, params, model, model_admin, field_path)

        self.title = "Timeseries Active"


@admin.register(Platform)
class PlatformAdmin(admin.GISModelAdmin):
    ordering = ["name", "mooring_site_desc", "ndbc_site_id"]
    inlines = [AlertInline, TimeSeriesInline, ProgramAttributionInline]

    actions = ["remove_end_time", "disable_timeseries", "enable_timeseries"]
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

    list_display = ["name", "mooring_site_desc", "ndbc_site_id"]
    list_filter = [
        "timeseries__dataset__server__name",
        ("timeseries__active", TimeseriesActiveFilter),
        "timeseries__data_type__standard_name",
        "timeseries__dataset__name",
    ]

    @admin.action(
        description="Remove end time for timeseries that have an end time in the last year",
    )
    def remove_end_time(self, request, queryset):
        platforms = []
        timeseries = []

        year = timedelta(days=365)

        year_ago = timezone.now() - year

        for platform in queryset.iterator():
            platforms.append(platform)
            for ts in platform.timeseries_set.filter(end_time__gte=year_ago):
                ts.end_time = None
                timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ["end_time"])

        self.message_user(
            request,
            (
                f"Removed end time for {len(timeseries)} timeseries with an end time "
                f"since {year_ago} from {len(platforms)} platform"
            ),
        )

    @admin.action(description="Disable updating of timeseries")
    def disable_timeseries(self, request, queryset):
        platforms = []
        timeseries = []

        for platform in queryset.iterator():
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

        for platform in queryset.iterator():
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

    actions = ["disable_timeseries", "enable_timeseries"]

    @admin.action(description="Disable updating of timeseries")
    def disable_timeseries(self, request, queryset):
        datasets = []
        timeseries = []

        for server in queryset.iterator():
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

        for server in queryset.iterator():
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


@admin.register(ErddapDataset)
class ErddapDatasetAdmin(admin.ModelAdmin):
    ordering = ["name"]
    search_fields = ["name", "server__name", "server__base_url"]

    actions = ["disable_timeseries", "enable_timeseries"]

    @admin.action(description="Disable updating of timeseries")
    def disable_timeseries(self, request, queryset):
        datasets = []
        timeseries = []

        for dataset in queryset.iterator():
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

        for dataset in queryset.iterator():
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
