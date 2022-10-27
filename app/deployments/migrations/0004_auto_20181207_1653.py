# Generated by Django 2.1.2 on 2018-12-07 16:53

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deployments", "0003_auto_20181207_1649"),
    ]

    operations = [
        migrations.AlterField(
            model_name="deployment",
            name="mooring_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="deployments.MooringType",
            ),
        ),
    ]
