from django.db import models

from .choice_enum import ChoiceEnum
from .timeseries import TimeSeries


class FloodLevel(models.Model):
    timeseries = models.ForeignKey(
        TimeSeries,
        on_delete=models.CASCADE,
        related_name="flood_levels",
    )

    min_value = models.FloatField()

    class Level(ChoiceEnum):
        MINOR = "Minor"
        MODERATE = "Moderate"
        MAJOR = "Major"

        OTHER = "Other"

    level = models.CharField("Level", choices=Level.choices(), max_length=16)
    level_other = models.CharField(
        "Optional name for 'Other level'",
        blank=True,
        null=True,
    )
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        name = self.level_other if self.level_other else self.Level[self.level].value
        return f"{name} - {self.min_value}"
