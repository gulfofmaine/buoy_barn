# Generated by Django 2.1.5 on 2019-03-28 17:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deployments", "0024_auto_20190328_1540"),
    ]

    operations = [
        migrations.AlterField(
            model_name="erddapdataset",
            name="name",
            field=models.SlugField(
                help_text=(
                    "Or as ERDDAP knows it as the Dataset ID. "
                    "EX: 'Dataset ID: A01_accelerometer_all'"
                ),
                max_length=256,
            ),
        ),
        migrations.AlterField(
            model_name="erddapserver",
            name="name",
            field=models.SlugField(
                max_length=64,
                null=True,
                verbose_name="Server Name",
            ),
        ),
    ]
