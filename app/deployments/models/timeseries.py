from datetime import datetime, timedelta

from django.db import models

from .buffer_type import BufferType
from .data_type import DataType
from .erddap_dataset import ErddapDataset
from .platform import Platform


class TimeSeriesQuerySet(models.QuerySet):
    def refreshable(self, include_retired: bool = False):
        """The timeseries the refresh path actually fetches.

        The definition of "currently refreshed", used by both
        `ErddapDataset.group_timeseries_by_constraint_and_type` (which does the fetching) and
        the `constraint_group.info` metric in `buoy_barn.observability.freshness`.

        `include_retired`: drop the `end_time__isnull` from the filter so a series that
        was wrongly retired (`end_time` set) can be offered back to a refresh that was asked
        to try clearing it (see `refresh_dataset(clear_end_time=True)`). `active=True` still
        applies, this is about recovering a mistaken retirement, not refreshing series an
        admin deliberately turned off.
        """
        queryset = self.filter(active=True)
        if not include_retired:
            queryset = queryset.filter(end_time__isnull=True)
        return queryset


class TimeSeriesManager(models.Manager.from_queryset(TimeSeriesQuerySet)):
    def by_dataset_slug(self, slug: str):
        server, dataset = slug.split("-", 2)
        return self.filter(dataset__server__name=server, dataset__name=dataset)


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

    class TimeSeriesType(models.TextChoices):
        OBSERVATION = "Observation"
        PREDICTION = "Prediction"
        FORECAST = "Forecast"
        CLIMATOLOGY = "Climatology"

    FUTURE_TYPES = {TimeSeriesType.PREDICTION, TimeSeriesType.FORECAST}

    timeseries_type = models.CharField(
        max_length=50,
        choices=TimeSeriesType.choices,
        default=TimeSeriesType.OBSERVATION,
        help_text="Is this timeseries an observation, prediction, forecast, or climatology?",
    )

    class Highlighted(models.TextChoices):
        NO = "No"
        BEFORE = "Before"
        AFTER = "After"

    extrema = models.BooleanField(
        default=False,
        help_text=("Is this timeseries an extrema (high or low), or regularly spaced?"),
    )

    highlighted = models.CharField(
        max_length=50,
        choices=Highlighted,
        default=Highlighted.NO,
        help_text=(
            "Should this timeseries be elevated to current conditions/latest values, "
            "and should it go before or after the existing set?"
        ),
    )

    depth = models.FloatField(null=True, blank=True)

    start_time = models.DateTimeField(default=datetime.now)
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
    extrema_values = models.JSONField(
        "Calculated extremes (and tides if applicable) for the loaded window (last 1 or next 7 days)",
        default=dict,
    )
    active = models.BooleanField(
        default=True,
        help_text="Should this dataset be currently updated?",
    )

    DATUMS = {
        "datum_mhhw_meters": "Mean Higher High Water (MHHW) offset in meters",
        "datum_mhw_meters": "Mean High Water (MHW) offset in meters",
        "datum_mtl_meters": "Mean Tide Level (MTL) offset in meters",
        "datum_msl_meters": "Mean Sea Level (MSL) offset in meters",
        "datum_mlw_meters": "Mean Low Water (MLW) offset in meters",
        "datum_mllw_meters": "Mean Lower Low Water (MLLW) offset in meters",
    }

    datum_mhhw_meters = models.FloatField(
        "Mean Higher High Water (MHHW) offset in meters",
        null=True,
        blank=True,
    )
    datum_mhw_meters = models.FloatField(
        "Mean High Water (MHW) offset in meters",
        null=True,
        blank=True,
    )
    datum_mtl_meters = models.FloatField(
        "Mean Tide Level (MTL) offset in meters",
        null=True,
        blank=True,
    )
    datum_msl_meters = models.FloatField(
        "Mean Sea Level (MSL) offset in meters",
        null=True,
        blank=True,
    )
    datum_mlw_meters = models.FloatField(
        "Mean Low Water (MLW) offset in meters",
        null=True,
        blank=True,
    )
    datum_mllw_meters = models.FloatField(
        "Mean Lower Low Water (MLLW) offset in meters",
        null=True,
        blank=True,
    )

    objects = TimeSeriesManager()

    class Meta:
        ordering = ["data_type"]
        verbose_name_plural = "Time Series"

    def __str__(self):
        return f"{self.platform.name} - {self.data_type.standard_name} - {self.depth}"

    def dataset_url(self, file_type: str, time_after: datetime = None) -> str:
        server = self.dataset.server.connection()
        server.dataset_id = self.dataset.name
        server.response = file_type
        server.protocol = "tabledap"

        constraints = {} if not self.constraints else self.constraints.copy()

        if not time_after:
            time_after = datetime.utcnow() - timedelta(hours=24)

        constraints["time>="] = time_after

        server.variables = ["time", self.variable]
        server.constraints = constraints

        return server.get_download_url()
