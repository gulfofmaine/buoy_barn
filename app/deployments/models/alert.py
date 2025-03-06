from datetime import date

from django.db import models

from .choice_enum import ChoiceEnum
from .platform import Platform


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
            f"{self.platform.name} - {self.level} - {self.start_time}:{self.end_time} - {self.message}"
        )

    @property
    def json(self):
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "message": self.message,
            "level": self.level,
        }
