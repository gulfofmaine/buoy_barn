from datetime import timedelta

from django.contrib.gis import admin
from django.utils import timezone

from .models import (
    Alert,
    Program,
    Platform,
    MooringType,
    StationType,
    DataType,
    BufferType,
    TimeSeries,
    ProgramAttribution,
    ErddapServer,
    ErddapDataset,
)


class TimeSeriesInline(admin.TabularInline):
    model = TimeSeries
    extra = 0


class ProgramAttributionInline(admin.TabularInline):
    model = ProgramAttribution
    extra = 0


class AlertInline(admin.TabularInline):
    model = Alert
    extra = 0


class PlatformAdmin(admin.GeoModelAdmin):
    ordering = ["name"]
    inlines = [AlertInline, TimeSeriesInline, ProgramAttributionInline]

    actions = ["remove_end_time"]

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
            f"Removed end time for {len(timeseries)} timeseries with an end time since {year_ago} from {len(platforms)} platform",
        )

    remove_end_time.short_description = (
        "Remove end time for timeseries that have an end time in the last year"
    )


admin.site.register(Program)
admin.site.register(Platform, PlatformAdmin)
admin.site.register(MooringType)
admin.site.register(StationType)
admin.site.register(DataType)
admin.site.register(BufferType)
admin.site.register(ErddapServer)
admin.site.register(ErddapDataset)
