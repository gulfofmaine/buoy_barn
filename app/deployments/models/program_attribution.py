from django.db import models

from .platform import Platform
from .program import Program


class ProgramAttribution(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE)
    attribution = models.TextField()

    def __str__(self):
        return f"{self.platform.name} - {self.program.name}"

    @property
    def json(self):
        return {"program": self.program.json, "attribution": self.attribution}
