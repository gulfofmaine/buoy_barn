# Generated by Django 4.2.2 on 2023-06-16 18:21

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("deployments", "0040_erddapserver_request_refresh_time_seconds_and_more"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="erddapdataset",
            constraint=models.UniqueConstraint(
                fields=("name", "server"),
                name="unique_dataset",
            ),
        ),
    ]
