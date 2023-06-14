# Generated by Django 3.1.1 on 2020-09-22 17:26

from django.db import migrations


def empty_reverse(apps, schema_editor):
    pass


def create_mayflower_data_types(apps, schema_editor):
    data_types = [
        ("relative_humidity", None, "Relative Humidity", "percent"),
        (
            "sea_surface_wave_from_direction",
            None,
            "Wave From Direction",
            "degrees_true",
        ),
        ("sea_water_velocity_m", None, "Sea Water Velocity", "m/s"),
    ]

    DataType = apps.get_model("deployments", "DataType")

    for standard_name, short_name, long_name, unit in data_types:
        instance = DataType(
            standard_name=standard_name,
            short_name=short_name,
            long_name=long_name,
            units=unit,
        )
        instance.save()


class Migration(migrations.Migration):
    dependencies = [("deployments", "0030_auto_20200917_2220")]

    operations = [migrations.RunPython(create_mayflower_data_types, empty_reverse)]
