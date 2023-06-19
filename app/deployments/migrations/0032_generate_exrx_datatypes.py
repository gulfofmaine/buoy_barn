# Generated by Django 3.1.1 on 2020-09-30 14:51

from django.db import migrations


def empty_reverse(apps, schema_editor):
    pass


def create_exrx_data_types(apps, schema_editor):
    data_types = [
        (
            "oxygen_concentration_in_sea_water",
            "Dissolved O2",
            "Oxygen Concentration In Sea Water",
            "mg/L",
        ),
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
    dependencies = [("deployments", "0031_generate_mayflower_datatypes")]

    operations = [migrations.RunPython(create_exrx_data_types, empty_reverse)]
