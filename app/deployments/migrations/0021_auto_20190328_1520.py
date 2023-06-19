# Generated by Django 2.1.5 on 2019-03-28 15:20

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("deployments", "0020_timeseries_dataset"),
    ]

    operations = [
        migrations.AddField(
            model_name="timeseries",
            name="update_time",
            field=models.DateTimeField(
                auto_now=True,
                help_text="When this value was last refreshed",
            ),
        ),
        migrations.AddField(
            model_name="timeseries",
            name="value",
            field=models.FloatField(
                help_text="Most recent value from ERDDAP",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="timeseries",
            name="value_time",
            field=models.DateTimeField(
                help_text="Time of the most recent value",
                null=True,
            ),
        ),
    ]
