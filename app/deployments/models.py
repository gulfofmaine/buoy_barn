from collections import defaultdict
from datetime import date
from enum import Enum
import logging

from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField
from erddapy import ERDDAP
from memoize import memoize
import pandas as pd
from requests import HTTPError

from deployments.utils.erddap_datasets import filter_dataframe, retrieve_dataframe


logger = logging.getLogger(__name__)


class ChoiceEnum(Enum):
    """ Special Enum that can format it's options for a django choice field"""

    @classmethod
    def choices(cls):
        return tuple((x.name, x.value) for x in cls)


class Program(models.Model):
    name = models.CharField(max_length=50)
    website = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def json(self):
        return {"name": self.name, "website": self.website}


class Platform(models.Model):
    name = models.CharField("Platform name", max_length=50)
    mooring_site_desc = models.TextField("Mooring Site Description")
    active = models.BooleanField(default=True)

    programs = models.ManyToManyField(Program, through="ProgramAttribution")

    ndbc_site_id = models.CharField(max_length=100, null=True, blank=True)
    uscg_light_letter = models.CharField(max_length=10, null=True, blank=True)
    uscg_light_num = models.CharField(max_length=16, null=True, blank=True)
    watch_circle_radius = models.IntegerField(null=True, blank=True)

    geom = models.PointField("Location", null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def current_deployment(self):
        return self.deployment_set.filter(end_time=None).order_by("-start_time").first()

    @property
    def location(self):
        if self.current_deployment:
            return self.current_deployment.geom
        if self.geom:
            return self.geom
        return None

    def group_timeseries_by_erddap_dataset(self):
        datasets = defaultdict(list)

        for ts in self.timeseries_set.filter(end_time=None).select_related(
            "data_type", "erddap_server"
        ):
            datasets[
                (ts.erddap_server, ts.erddap_dataset, tuple(ts.constraints.items()))
            ].append(ts)

        return datasets

    @memoize(timeout=30 * 60)
    def latest_erddap_values(self):
        readings = []

        for (
            (server, dataset, constraints),
            timeseries,
        ) in self.group_timeseries_by_erddap_dataset().items():
            try:
                df = retrieve_dataframe(server, dataset, dict(constraints), timeseries)

                for series in timeseries:
                    filtered_df = filter_dataframe(df, series.variable)
                    try:
                        row = filtered_df.iloc[-1]
                    except IndexError:
                        logger.warning(
                            f"Unable to find position in dataframe for {self.name} - {series.variable}"
                        )
                        reading = None
                        time = None
                    else:
                        reading = row[series.variable]
                        time = row["time"].strftime("%Y-%m-%dT%H:%M:%SZ")
                    readings.append(
                        {
                            "value": reading,
                            "time": time,
                            "depth": series.depth,
                            "data_type": series.data_type.json,
                            "server": series.erddap_server.base_url,
                            "variable": series.variable,
                            "constraints": series.constraints,
                            "dataset": series.erddap_dataset,
                            "start_time": series.start_time,
                        }
                    )
            except HTTPError:
                for series in timeseries:
                    readings.append(
                        {
                            "value": None,
                            "time": None,
                            "depth": series.depth,
                            "data_type": series.data_type.json,
                            "server": series.erddap_server.base_url,
                            "variable": series.variable,
                            "constraints": series.constraints,
                            "dataset": series.erddap_dataset,
                        }
                    )
        return readings

    def current_alerts(self):
        return self.alerts.filter(end_time__gt=date.today()) | self.alerts.filter(
            end_time=None
        )


class ProgramAttribution(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE)
    attribution = models.TextField()

    def __str__(self):
        return f"{self.platform.name} - {self.program.name}"

    @property
    def json(self):
        return {"program": self.program.json, "attribution": self.attribution}


class MooringType(models.Model):
    name = models.CharField("Mooring type", max_length=64)

    def __str__(self):
        return self.name


class StationType(models.Model):
    name = models.CharField("Station type", max_length=64)

    def __str__(self):
        return self.name


class Deployment(models.Model):
    deployment_name = models.CharField("Deployment platform name", max_length=50)

    platform = models.ForeignKey(Platform, on_delete=models.CASCADE)

    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    geom = models.PointField("Location")
    magnetic_variation = models.FloatField()
    water_depth = models.FloatField()

    mooring_type = models.ForeignKey(
        MooringType, on_delete=models.CASCADE, null=True, blank=True
    )
    mooring_site_id = models.TextField()

    station_type = models.ForeignKey(StationType, on_delete=models.CASCADE)

    def __str__(self):
        if self.end_time:
            return f"{self.platform.name}: {self.deployment_name} - ({self.start_time.date()} - {self.end_time.date()} - {self.start_time - self.end_time})"
        return f"{self.platform.name}: {self.deployment_name} - (launched: {self.start_time.date()})"


class DataType(models.Model):
    standard_name = models.CharField(max_length=128)
    short_name = models.CharField(max_length=16, null=True, blank=True)
    long_name = models.CharField(max_length=128)
    units = models.CharField(max_length=64)

    # preffered_unit = models.CharField(max_length=16)

    def __str__(self):
        return f"{self.standard_name} - {self.long_name} ({self.units})"

    @property
    def json(self):
        return {
            "standard_name": self.standard_name,
            "short_name": self.short_name,
            "long_name": self.long_name,
            "units": self.units,
        }


class BufferType(models.Model):
    name = models.CharField("Buffer type", max_length=64)

    def __str__(self):
        return self.name


class ErddapServer(models.Model):
    name = models.CharField("Server Name", max_length=64, null=True)
    base_url = models.CharField("ERDDAP API base URL", max_length=256)
    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, null=True, blank=True
    )
    contact = models.TextField("Contact information", null=True, blank=True)

    def __str__(self):
        if self.name:
            return self.name
        return self.base_url

    def connection(self):
        return ERDDAP(self.base_url)


class TimeSeries(models.Model):
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE)
    data_type = models.ForeignKey(DataType, on_delete=models.CASCADE)
    variable = models.CharField(max_length=256)
    constraints = JSONField(
        "Extra ERDDAP constraints",
        help_text="Extra constratints needed when querying ERDDAP (for example: when datasets have multiple platforms)",
        null=True,
        blank=True,
    )

    depth = models.FloatField(null=True, blank=True)

    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    buffer_type = models.ForeignKey(
        BufferType, on_delete=models.CASCADE, null=True, blank=True
    )
    erddap_dataset = models.CharField(max_length=256, null=True, blank=True)
    erddap_server = models.ForeignKey(
        ErddapServer, on_delete=models.CASCADE, null=True, blank=True
    )

    def __str__(self):
        return f"{self.platform.name} - {self.data_type.standard_name} - {self.depth}"


class Alert(models.Model):
    platform = models.ForeignKey(
        Platform, on_delete=models.CASCADE, related_name="alerts"
    )
    start_time = models.DateField(default=date.today)
    end_time = models.DateField(blank=True, null=True)
    message = models.TextField()

    class Level(ChoiceEnum):
        INFO = "info"
        WARNING = "warning"
        DANGER = "danger"

    level = models.CharField(
        "Alert level", choices=Level.choices(), default=Level.INFO, max_length=16
    )

    def __str__(self):
        return f"{self.platform.name} - {self.level} - {self.start_time}:{self.end_time} - {self.message}"

    @property
    def json(self):
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "message": self.message,
            "level": self.level,
        }


class Forecast(models.Model):
    erddap_server = models.ForeignKey(ErddapServer, on_delete=models.CASCADE)
    erddap_dataset = models.CharField(max_length=256)
    invertLongitude = models.BooleanField()

    name = models.TextField()

    variable = models.CharField(max_length=256)

    TYPES = (
        ("waveHeight", "Wave Height"),
        ("wavePeriod", "Wave Period"),
        ("waveDirection", "Wave Direction"),
        ("airTemperature", "Air Temperature"),
        ("windSpeed", "Wind Speed"),
        ("windDirection", "Wind Direction"),
    )
    forecast_type = models.CharField(choices=TYPES, max_length=32)

    def __str__(self):
        return self.name

    @memoize(timeout=15 * 60)
    def latest_coverage_time(self):
        conn = self.erddap_server.connection()
        conn.dataset_id = self.erddap_dataset

        info_csv = conn.get_info_url(response="csv")

        try:
            df = pd.read_csv(info_csv)
        except HTTPError:
            return None

        try:
            end = df[df["Attribute Name"] == "time_coverage_end"]["Value"]
            return end.values[0]
        except AttributeError:
            return None
