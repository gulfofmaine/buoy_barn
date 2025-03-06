import logging
import typing
from collections import defaultdict

from django.db import models

from .erddap_server import ErddapServer

if typing.TYPE_CHECKING:
    from .timeseries import TimeSeries

logger = logging.getLogger(__name__)


class ErddapDataset(models.Model):
    name = models.SlugField(
        max_length=256,
        help_text="Or as ERDDAP knows it as the Dataset ID. EX: 'Dataset ID: A01_accelerometer_all'",
    )
    public_name = models.CharField(
        max_length=256,
        blank=True,
        null=True,
        help_text="The name of the dataset as it should be displayed in the UI",
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
            import requests

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
            import requests

            try:
                requests.get(hc_url, timeout=5)
            except requests.RequestException as error:
                logger.error(
                    f"Unable to send healthcheck completion for {self.name} due to error: {error}",
                    exc_info=True,
                )

    def group_timeseries_by_constraint_and_type(self) -> dict[tuple[tuple, str], list["TimeSeries"]]:
        """Groups the datasets active timeseries by constraints and types"""
        groups = defaultdict(list)

        for ts in (
            self.timeseries_set.filter(end_time=None, active=True)
            .select_related("platform")
            .prefetch_related("data_type")
        ):
            try:
                groups[(tuple((ts.constraints or {}).items()), ts.timeseries_type)].append(ts)
            except AttributeError as e:
                logger.error(f"Unable to set constraints for timeseries {ts} due to {e}")

        return groups
