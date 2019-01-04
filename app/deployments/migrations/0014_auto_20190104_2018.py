# Generated by Django 2.1.2 on 2019-01-04 20:18

import datetime
import deployments.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("deployments", "0013_alert")]

    operations = [
        migrations.AddField(
            model_name="alert",
            name="level",
            field=models.CharField(
                choices=[
                    ("INFO", "info"),
                    ("WARNING", "warning"),
                    ("DANGER", "danger"),
                ],
                default=deployments.models.Alert.Level("info"),
                max_length=16,
                verbose_name="Alert level",
            ),
        ),
        migrations.AlterField(
            model_name="alert",
            name="start_time",
            field=models.DateField(default=datetime.date(2019, 1, 4)),
        ),
    ]
