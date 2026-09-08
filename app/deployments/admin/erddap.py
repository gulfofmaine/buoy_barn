"""The ErddapServer and ErddapDataset admins, and the dataset's refresh-status filter."""

from datetime import timedelta
from typing import Any

from django.contrib.admin import SimpleListFilter
from django.contrib.gis import admin
from django.db.models.query import QuerySet
from django.http.request import HttpRequest
from django.utils import timezone
from django.utils.html import format_html
from django_object_actions import DjangoObjectActions, action

from ..models import ErddapDataset, ErddapServer, TimeSeries
from ..tasks import refresh
from .displays import timeseries_status
from .system_messages import (
    SystemMessageListFilter,
    SystemMessageSidebarMixin,
    system_message_status,
)
from .timeseries import TimeSeriesInline


@admin.register(ErddapServer)
class ErddapServerAdmin(SystemMessageSidebarMixin, DjangoObjectActions, admin.ModelAdmin):
    ordering = ["name"]

    actions = ["disable_timeseries", "enable_timeseries", "refresh_server"]
    change_actions = ["refresh_erddap_server"]

    @action(description="Refresh all datasets for this server")
    def refresh_erddap_server(self, request, obj):
        refresh.refresh_server.delay(obj.id, healthcheck=False)
        self.message_user(
            request,
            f"Queued all datasets for server '{obj}' to be refreshed.",
        )

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
class ErddapDatasetAdmin(SystemMessageSidebarMixin, DjangoObjectActions, admin.ModelAdmin):
    ordering = ["name"]
    search_fields = ["name", "server__name", "server__base_url"]
    list_display = [
        "name",
        timeseries_status,
        system_message_status,
        "server",
        "refresh_status",
    ]
    list_filter = [SystemMessageListFilter, "server__name", RefreshStatusListFilter]
    inlines = [TimeSeriesInline]

    actions = ["disable_timeseries", "enable_timeseries", "refresh_dataset"]
    change_actions = ["refresh_erddap_dataset"]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        queryset = super().get_queryset(request)
        queryset = queryset.select_related("server").prefetch_related(
            "timeseries_set",
            "timeseries_set__data_type",
            "timeseries_set__platform",
        )
        return queryset

    @admin.display(description="Refresh attempted")
    def refresh_status(self, obj: ErddapDataset):
        if obj.refresh_attempted is None:
            return format_html(
                "<span style='color: {};'>{}</span>",
                "gray",
                "Never refreshed",
            )

        now = timezone.now()
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)

        last_refreshed = f"Last refreshed at: {obj.refresh_attempted:%Y-%m-%d %H:%M}"
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

    @action(description="Refresh this dataset")
    def refresh_erddap_dataset(self, request, obj):
        refresh.refresh_dataset.delay(obj.id, healthcheck=False)
        self.message_user(
            request,
            f"Queued dataset '{obj}' for refresh.",
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
