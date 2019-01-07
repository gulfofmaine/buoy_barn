from django.contrib.gis import admin

from .models import (
    Alert,
    Forecast,
    Program,
    Platform,
    Deployment,
    MooringType,
    StationType,
    DataType,
    BufferType,
    TimeSeries,
    ProgramAttribution,
    ErddapServer,
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


class DeploymentAdmin(admin.GeoModelAdmin):
    save_as = True


class PlatformAdmin(admin.GeoModelAdmin):
    ordering = ["name"]
    inlines = [AlertInline, TimeSeriesInline, ProgramAttributionInline]


admin.site.register(Program)
admin.site.register(Platform, PlatformAdmin)
admin.site.register(Deployment, DeploymentAdmin)
admin.site.register(MooringType)
admin.site.register(StationType)
admin.site.register(DataType)
admin.site.register(BufferType)
admin.site.register(ErddapServer)
admin.site.register(Forecast)
