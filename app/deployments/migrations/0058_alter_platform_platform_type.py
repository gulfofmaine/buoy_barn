# Generated by Django 5.1.4 on 2025-04-02 18:05

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("deployments", "0057_platform_visible_climatology_platform_visible_dev_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="platform",
            name="platform_type",
            field=models.CharField(
                choices=[
                    ("Buoy", "Buoy"),
                    ("Tide Station", "Tide Station"),
                    ("Overland Flood", "Overland Flood"),
                    ("Virtual", "Virtual"),
                ],
                default="Buoy",
                max_length=50,
            ),
        ),
    ]
