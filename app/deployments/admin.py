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

    actions = ["remove_end_time", "disable_timeseries", "enable_timeseries"]

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

    def disable_timeseries(self, request, queryset):
        platforms = []
        timeseries = []


        for platform in queryset.iterator():
            platforms.append(platform)
            for ts in platform.timeseries_set.all():
                ts.active = False
                timeseries.append(ts)
        
        TimeSeries.objects.bulk_update(timeseries, ['active'])

        self.message_user(
            request,
            f"Disabled {len(timeseries)} timeseries from {len(platforms)} platforms"
        )
    
    disable_timeseries.short_description = "Disable updating of timeseries"
    
    def enable_timeseries(self, request, queryset):
        platforms = []
        timeseries = []

        for platform in queryset.iterator():
            platforms.append(platform)
            for ts in platform.timeseries_set.all():
                ts.active = True
                timeseries.append(ts)
        
        TimeSeries.objects.bulk_update(timeseries, ['active'])

        self.message_user(
            request,
            f"Enable {len(timeseries)} timeseries from {len(platforms)} platforms"
        )
    
    enable_timeseries.short_description = "Enable updating of timeseries"


class ErddapServerAdmin(admin.ModelAdmin):
    ordering = ["name"]

    actions = ["disable_timeseries", "enable_timeseries"]

    def disable_timeseries(self, request, queryset):
        datasets = []
        timeseries = []

        for server in queryset.iterator():
            for dataset in server.erddapdataset_set.all():
                datasets.append(dataset)
                for ts in dataset.timeseries_set.all():
                    ts.active = False
                    timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ['active'])

        self.message_user(
            request,
            f"Disabled {len(timeseries)} timeseries from {len(datasets)} datasets"
        )
    
    disable_timeseries.short_description = "Disable updating of timeseries"
    
    def enable_timeseries(self, request, queryset):
        datasets = []
        timeseries = []

        for server in queryset.iterator():
            for dataset in server.erddapdataset_set.all():
                datasets.append(dataset)
                for ts in dataset.timeseries_set.all():
                    ts.active = True
                    timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ['active'])

        self.message_user(
            request,
            f"Disabled {len(timeseries)} timeseries from {len(datasets)} datasets"
        )
    
    enable_timeseries.short_description = "Enable updating of timeseries"



class ErddapDatasetAdmin(admin.ModelAdmin):
    ordering = ["name"]

    actions = ["disable_timeseries", "enable_timeseries"]

    def disable_timeseries(self, request, queryset):
        datasets = []
        timeseries = []

        for dataset in queryset.iterator():
            datasets.append(dataset)
            for ts in dataset.timeseries_set.all():
                ts.active = False
                timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ['active'])

        self.message_user(
            request,
            f"Disabled {len(timeseries)} timeseries from {len(datasets)} datasets"
        )
    
    disable_timeseries.short_description = "Disable updating of timeseries"
    
    def enable_timeseries(self, request, queryset):
        datasets = []
        timeseries = []

        for dataset in queryset.iterator():
            datasets.append(dataset)
            for ts in dataset.timeseries_set.all():
                ts.active = True
                timeseries.append(ts)

        TimeSeries.objects.bulk_update(timeseries, ['active'])

        self.message_user(
            request,
            f"Disabled {len(timeseries)} timeseries from {len(datasets)} datasets"
        )
    
    enable_timeseries.short_description = "Enable updating of timeseries"



admin.site.register(Program)
admin.site.register(Platform, PlatformAdmin)
admin.site.register(MooringType)
admin.site.register(StationType)
admin.site.register(DataType)
admin.site.register(BufferType)
admin.site.register(ErddapServer, ErddapServerAdmin)
admin.site.register(ErddapDataset, ErddapDatasetAdmin)
