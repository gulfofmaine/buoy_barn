from django.db import models

from .platform import Platform


class PlatformLink(models.Model):
    platform = models.ForeignKey(
        Platform,
        on_delete=models.CASCADE,
        related_name="links",
    )
    title = models.CharField("URL title", max_length=128)
    url = models.CharField("URL", max_length=512)
    alt_text = models.TextField("Alternate text", blank=True, null=True)

    def __str__(self):
        return self.title
