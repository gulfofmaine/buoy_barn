import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from enum import Enum

import requests
from django.contrib.gis.db import models
from erddapy import ERDDAP

logger = logging.getLogger(__name__)


class ChoiceEnum(Enum):
    """Special Enum that can format it's options for a django choice field"""

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
    def location(self):
        if self.geom:
            return self.geom
        return None

    def current_alerts(self):
        alerts = []
        for alert in self.alerts.all():
            if not alert.end_time or date.today() < alert.end_time:
                alerts.append(alert)
        return alerts


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


class DataType(models.Model):
    standard_name = models.CharField(max_length=128)
    short_name = models.CharField(max_length=64, null=True, blank=True)
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

    class Meta:
        ordering = ["standard_name"]


class BufferType(models.Model):
    name = models.CharField("Buffer type", max_length=64)

    def __str__(self):
        return self.name


class ErddapServer(models.Model):
    name = models.SlugField("Server Name", max_length=64, null=True)
    base_url = models.CharField("ERDDAP API base URL", max_length=256)
    program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    contact = models.TextField("Contact information", null=True, blank=True)
    healthcheck_url = models.URLField(
        "URL to send healthchecks to at beginning and end of processing",
        null=True,
        blank=True,
    )
    proxy_cors = models.BooleanField(
        "Proxy CORS requests",
        default=True,
        help_text=(
            "Use Buoy Barn to proxy requests to remote ERDDAP server, "
            "if the remote server does not support CORS"
        ),
    )
    request_refresh_time_seconds = models.FloatField(
        "Refresh request time in seconds",
        default=0,
        help_text=(
            "Minimum number of seconds to attempt to delay between requests. "
            "If dataset refreshes are triggered independently "
            "(e.g. via ERDDAP subscriptions) they might ignore this."
        ),
    )
    request_timeout_seconds = models.PositiveIntegerField(
        "Request timeout in seconds",
        default=60,
        help_text=("Seconds before requests time out."),
    )

    def __str__(self):
        if self.name:
            return self.name
        return self.base_url

    def connection(self):
        return ERDDAP(self.base_url)

    def healthcheck_start(self):
        """Signal that a process has started with Healthchecks.io"""
        hc_url = self.healthcheck_url

        if hc_url:
            try:
                requests.get(hc_url + "/start", timeout=5)
            except requests.RequestException as error:
                logger.error(
                    f"Unable to send healthcheck start for {self.name} due to: {error}",
                    exc_info=True,
                )

    def healthcheck_complete(self):
        """Signal that a process has completed with Healthchecks.io"""
        hc_url = self.healthcheck_url

        if hc_url:
            try:
                requests.get(hc_url, timeout=5)
            except requests.RequestException as error:
                logger.error(
                    f"Unable to send healthcheck completion for {self.name} due to error: {error}",
                    exc_info=True,
                )


class ErddapDataset(models.Model):
    name = models.SlugField(
        max_length=256,
        help_text="Or as ERDDAP knows it as the Dataset ID. EX: 'Dataset ID: A01_accelerometer_all'",
    )
    server = models.ForeignKey(ErddapServer, on_delete=models.CASCADE)

    healthcheck_url = models.URLField(
        "URL to send healthchecks to at beginning and end of processing",
        null=True,
        blank=True,
    )
    refresh_attempted = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Last time that Buoy Barn attempted to refresh this dataset",
    )
    greater_than_hourly = models.BooleanField(
        default=False,
        help_text=(
            "Select if this dataset should only be refreshed at intervals of "
            "longer than 1/hour between refreshes (say once per day). "
            "Ask Alex to setup refreshing at a different rate."
        ),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name", "server"], name="unique_dataset"),
        ]

    def __str__(self):
        return f"{self.server.name} - {self.name}"

    @property
    def slug(self):
        return f"{self.server.name}-{self.name}"

    def healthcheck_start(self):
        """Signal that a process has started with Healthchecks.io"""
        hc_url = self.healthcheck_url

        if hc_url:
            try:
                requests.get(hc_url + "/start", timeout=5)
            except requests.RequestException as error:
                logger.error(
                    f"Unable to send healthcheck start for {self.name} due to: {error}",
                    exc_info=True,
                )

    def healthcheck_complete(self):
        """Signal that a process has completed with Healthchecks.io"""
        hc_url = self.healthcheck_url

        if hc_url:
            try:
                requests.get(hc_url, timeout=5)
            except requests.RequestException as error:
                logger.error(
                    f"Unable to send healthcheck completion for {self.name} due to error: {error}",
                    exc_info=True,
                )

    def group_timeseries_by_constraint(self):
        groups = defaultdict(list)

        for ts in self.timeseries_set.filter(end_time=None, active=True):
            try:
                groups[tuple((ts.constraints or {}).items())].append(ts)
            except AttributeError as e:
                logger.error(f"Unable to set constraint for timeseries {ts} due to {e}")

        return groups


class TimeSeries(models.Model):
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE)
    data_type = models.ForeignKey(DataType, on_delete=models.CASCADE)
    variable = models.CharField(max_length=256)
    constraints = models.JSONField(
        "Extra ERDDAP constraints",
        help_text=(
            "Extra constratints needed when querying ERDDAP "
            "(for example: when datasets have multiple platforms)"
        ),
        null=True,
        blank=True,
    )

    depth = models.FloatField(null=True, blank=True)

    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    buffer_type = models.ForeignKey(
        BufferType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    dataset = models.ForeignKey(ErddapDataset, on_delete=models.CASCADE)

    update_time = models.DateTimeField(
        auto_now=True,
        help_text="When this value was last refreshed",
    )

    value = models.FloatField(
        null=True,
        blank=True,
        help_text="Most recent value from ERDDAP",
    )
    value_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Time of the most recent value",
    )
    active = models.BooleanField(
        default=True,
        help_text="Should this dataset be currently updated?",
    )

    def __str__(self):
        return f"{self.platform.name} - {self.data_type.standard_name} - {self.depth}"

    def dataset_url(self, file_type: str, time_after: datetime = None) -> str:
        server = self.dataset.server.connection()
        server.dataset_id = self.dataset.name
        server.response = file_type
        server.protocol = "tabledap"

        if not self.constraints:
            constraints = {}
        else:
            constraints = self.constraints.copy()

        if not time_after:
            time_after = datetime.utcnow() - timedelta(hours=24)

        constraints["time>="] = time_after

        server.variables = ["time", self.variable]
        server.constraints = constraints

        return server.get_download_url()


class Alert(models.Model):
    platform = models.ForeignKey(
        Platform,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    start_time = models.DateField(default=date.today)
    end_time = models.DateField(blank=True, null=True)
    message = models.TextField()

    class Level(ChoiceEnum):
        INFO = "info"
        WARNING = "warning"
        DANGER = "danger"

    level = models.CharField(
        "Alert level",
        choices=Level.choices(),
        default=Level.INFO,
        max_length=16,
    )

    def __str__(self):
        return (
            f"{self.platform.name} - {self.level} "
            f"- {self.start_time}:{self.end_time} - {self.message}"
        )

    @property
    def json(self):
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "message": self.message,
            "level": self.level,
        }
