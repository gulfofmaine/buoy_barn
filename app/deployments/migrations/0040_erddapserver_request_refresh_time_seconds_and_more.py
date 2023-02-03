# Generated by Django 4.1.3 on 2022-12-20 00:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deployments", "0039_erddapserver_proxy_cors"),
    ]

    operations = [
        migrations.AddField(
            model_name="erddapserver",
            name="request_refresh_time_seconds",
            field=models.FloatField(
                default=0,
                help_text=(
                    "Minimum number of seconds to attempt to delay between requests. "
                    "If dataset refreshes are triggered independently (e.g. via ERDDAP subscriptions) "
                    "they might ignore this."
                ),
                verbose_name="Refresh request time in seconds",
            ),
        ),
        migrations.AddField(
            model_name="erddapserver",
            name="request_timeout_seconds",
            field=models.PositiveIntegerField(
                default=60,
                help_text="Seconds before requests time out.",
                verbose_name="Request timeout in seconds",
            ),
        ),
    ]