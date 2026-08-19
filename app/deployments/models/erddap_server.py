from django.db import models

from .program import Program


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

    mqtt_broker = models.CharField(
        "MQTT broker",
        null=True,
        blank=True,
        max_length=128,
    )
    mqtt_port = models.PositiveIntegerField(
        "MQTT Port",
        default=1883,
    )
    mqtt_username = models.CharField(
        "MQTT Username",
        null=True,
        blank=True,
        max_length=64,
    )
    mqtt_password = models.CharField(
        "MQTT Password",
        null=True,
        blank=True,
        max_length=64,
    )

    def __str__(self):
        if self.name:
            return self.name
        return self.base_url

    def connection(self):
        from erddapy import ERDDAP  # noqa: PLC0415

        return ERDDAP(self.base_url)

    def healthcheck_start(self):
        """Signal that a process has started with Healthchecks.io"""
        from deployments.utils.healthchecks import ping_healthcheck  # noqa: PLC0415

        ping_healthcheck(self.healthcheck_url, self.name, start=True)

    def healthcheck_complete(self):
        """Signal that a process has completed with Healthchecks.io"""
        from deployments.utils.healthchecks import ping_healthcheck  # noqa: PLC0415

        ping_healthcheck(self.healthcheck_url, self.name)
