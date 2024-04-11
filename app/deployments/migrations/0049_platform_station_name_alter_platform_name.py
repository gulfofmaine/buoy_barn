# Generated by Django 5.0.4 on 2024-04-11 16:47

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("deployments", "0048_rename_platformlinks_platformlink"),
    ]

    operations = [
        migrations.AddField(
            model_name="platform",
            name="station_name",
            field=models.CharField(default="", max_length=100, verbose_name="Platform name"),
        ),
        migrations.AlterField(
            model_name="platform",
            name="name",
            field=models.CharField(max_length=50, verbose_name="Platform slug/station_id"),
        ),
    ]
