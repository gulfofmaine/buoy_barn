# Generated by Django 5.0.4 on 2024-04-25 14:46

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("deployments", "0050_alter_platform_station_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="timeseries",
            name="highlighted",
            field=models.CharField(
                choices=[("No", "No"), ("Before", "Before"), ("After", "After")],
                default="No",
                help_text="Should this timeseries be elevated to current conditions/latest values, and should it go before or after the existing set?",
                max_length=50,
            ),
        ),
    ]
