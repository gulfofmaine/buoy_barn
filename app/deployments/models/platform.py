from datetime import date

from django.contrib.gis.db import models

from .program import Program


class Platform(models.Model):
    name = models.CharField("Platform slug/station_id", max_length=50)
    station_name = models.CharField("Platform name", max_length=100, default="", blank=True)
    mooring_site_desc = models.TextField("Mooring Site Description")
    active = models.BooleanField(default=True)

    class PlatformTypes(models.TextChoices):
        BUOY = "Buoy"
        TIDE_STATION = "Tide Station"
        OVERLAND_FLOOD = "Overland Flood"

    platform_type = models.CharField(
        max_length=50,
        choices=PlatformTypes,
        default=PlatformTypes.BUOY,
    )

    programs = models.ManyToManyField(Program, through="ProgramAttribution")

    ndbc_site_id = models.CharField(max_length=100, null=True, blank=True)
    uscg_light_letter = models.CharField(max_length=10, null=True, blank=True)
    uscg_light_num = models.CharField(max_length=16, null=True, blank=True)
    watch_circle_radius = models.IntegerField(null=True, blank=True)

    geom = models.PointField("Location", null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def location(self):
        if self.geom:
            return self.geom
        return None

    def current_alerts(self):
        alerts = [
            alert for alert in self.alerts.all() if not alert.end_time or date.today() < alert.end_time
        ]
        return alerts
