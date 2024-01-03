# Generated by Django 2.1.5 on 2019-03-28 15:40

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("deployments", "0023_auto_20190328_1539"),
    ]

    operations = [
        migrations.AlterField(
            model_name="erddapdataset",
            name="name",
            field=models.CharField(
                help_text=(
                    "Or as ERDDAP knows it as the Dataset ID. " "EX: 'Dataset ID: A01_accelerometer_all'"
                ),
                max_length=256,
            ),
        ),
    ]
