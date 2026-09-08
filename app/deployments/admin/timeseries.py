"""The TimeSeries admin, its inline, and the filter/inline it shares with other admins."""

from datetime import timedelta
from typing import Any

from django.contrib.admin import SimpleListFilter
from django.contrib.gis import admin
from django.db.models.query import QuerySet
from django.http.request import HttpRequest
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from ..models import FloodLevel, TimeSeries
from ..tasks import refresh
from .system_messages import SystemMessageSidebarMixin, system_message_status


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
class TimeSeriesAdmin(SystemMessageSidebarMixin, admin.ModelAdmin):
    model = TimeSeries
    inlines = [FloodLevelInline]

    # TimeSeriesAdmin is a plain ModelAdmin, so its sidebar template extends
    # admin/change_form.html rather than django_object_actions'.
    change_form_template = "admin/deployments/timeseries/change_form.html"

    autocomplete_fields = ["dataset", "data_type", "buffer_type"]
    readonly_fields = ["test_timeseries"]

    actions = ["refresh_timeseries"]

    list_display = [
        "platform",
        "value",
        "timeseries_status",
        system_message_status,
        "data_type",
        "dataset",
    ]
    list_filter = [
        TimesiersStatusListFilter,
        "active",
        "platform",
        "data_type",
        "dataset",
        "dataset__server",
    ]
    search_fields = [
        "platform__name",
        "data_type__standard_name",
        "data_type__short_name",
        "data_type__long_name",
        "data_type__units",
        "dataset__name",
    ]

    @admin.display(description="Timeseries status")
    def timeseries_status(self, instance: TimeSeries):
        now = timezone.now()
        hour_ago = now - timedelta(hours=24)
        day_ago = now - timedelta(days=1)

        if instance.value_time is None:
            return format_html("<span style='color: gray;'>{}</span>", "No data")
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
        # The system message badge reaches through each row's dataset to its server; without
        # these the changelist would issue two queries per row to find them.
        queryset = queryset.select_related("dataset", "dataset__server")
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
