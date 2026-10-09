"""The Platform admin and its inlines/filter."""

from datetime import datetime, timedelta

import requests
from django.contrib.admin import BooleanFieldListFilter
from django.contrib.gis import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.http.request import HttpRequest
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django_object_actions import DjangoObjectActions, action

from ..forms import ErddapImportForm
from ..models import Alert, Platform, PlatformLink, ProgramAttribution, TimeSeries
from ..tasks import refresh
from ..utils.erddap_loader import ImportResult, apply_import, plan_import
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


def import_summary(result: ImportResult) -> str:
    """What an ERDDAP import changed, for the admin message"""
    action = "Created" if result.platform_created else "Updated"
    summary = (
        f"{action} platform {result.platform}: {len(result.created)} timeseries created, "
        f"{len(result.updated)} updated"
    )
    if result.fields_updated:
        summary += f", {', '.join(result.fields_updated)} set"
    if result.location_updated:
        summary += ", location set"
    return summary + "."


class TimeseriesActiveFilter(BooleanFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path) -> None:  # noqa: PLR0913, PLR0917
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

    change_actions = ["refresh_platform_datasets", "import_erddap_dataset"]
    changelist_actions = ["import_from_erddap"]

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
        )
        return queryset

    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "import-erddap/",
                self.admin_site.admin_view(self.import_erddap_view),
                name="deployments_platform_import_erddap",
            ),
            *urls,
        ]

    def import_erddap_url(self, platform: Platform | None = None) -> str:
        url = reverse(f"{self.admin_site.name}:deployments_platform_import_erddap")
        if platform is not None:
            url += f"?platform={platform.pk}"
        return url

    @action(
        label="Import from ERDDAP",
        description="Create a platform and its timeseries from an ERDDAP dataset",
    )
    def import_from_erddap(self, request, queryset):
        return HttpResponseRedirect(self.import_erddap_url())

    @action(
        label="Import dataset from ERDDAP",
        description="Add or update timeseries for this platform from an ERDDAP dataset",
    )
    def import_erddap_dataset(self, request, obj):
        return HttpResponseRedirect(self.import_erddap_url(obj))

    def has_import_permission(self, request) -> bool:
        return request.user.has_perms(
            [
                "deployments.add_platform",
                "deployments.change_platform",
                "deployments.add_timeseries",
                "deployments.change_timeseries",
            ],
        )

    def import_erddap_view(self, request):
        """Preview, then apply, an import from an ERDDAP dataset's metadata.

        The preview is re-planned from ERDDAP when it is applied, rather than carried in
        the session, so what is saved always matches the current metadata.
        """
        if not self.has_import_permission(request):
            raise PermissionDenied

        if request.method == "POST":
            form = ErddapImportForm(request.POST)
        else:
            form = ErddapImportForm(initial={"platform": request.GET.get("platform")})

        plan = None
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            try:
                plan = plan_import(
                    data["server"],
                    data["dataset_id"],
                    data["constraints"],
                    platform=data["platform"],
                )
            except (requests.RequestException, ValueError) as e:
                form.add_error(
                    None,
                    f"Unable to load metadata for {data['dataset_id']} from {data['server']}: {e}",
                )

            if plan is not None and request.POST.get("step") == "apply":
                result = apply_import(
                    plan,
                    create=request.POST.getlist("create"),
                    update=request.POST.getlist("update"),
                    platform_fields=request.POST.getlist("platform_field"),
                    update_location=bool(request.POST.get("update_location")),
                    platform_name=data["new_platform_name"] or None,
                )
                if result.created or result.updated:
                    refresh.refresh_dataset.delay(result.dataset.id)

                self.message_user(request, import_summary(result))
                return HttpResponseRedirect(
                    reverse(
                        f"{self.admin_site.name}:deployments_platform_change",
                        args=[result.platform.pk],
                    ),
                )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Import from ERDDAP",
            "form": form,
            "plan": plan,
        }
        return TemplateResponse(request, "admin/deployments/platform/import_erddap.html", context)

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
