# Generated by Django 2.1.2 on 2018-12-07 16:39

import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="BufferType",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=64, verbose_name="Buffer type")),
            ],
        ),
        migrations.CreateModel(
            name="DataType",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("standard_name", models.CharField(max_length=128)),
                ("short_name", models.CharField(max_length=16)),
                ("long_name", models.CharField(max_length=128)),
                ("units", models.CharField(max_length=64)),
            ],
        ),
        migrations.CreateModel(
            name="Deployment",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "deployment_name",
                    models.CharField(
                        max_length=50,
                        verbose_name="Deployment platform name",
                    ),
                ),
                ("start_time", models.DateTimeField()),
                ("end_time", models.DateTimeField(blank=True, null=True)),
                (
                    "geom",
                    django.contrib.gis.db.models.fields.PointField(
                        srid=4326,
                        verbose_name="Location",
                    ),
                ),
                ("magnetic_variation", models.FloatField()),
                ("water_depth", models.FloatField()),
                ("mooring_site_id", models.TextField()),
            ],
        ),
        migrations.CreateModel(
            name="ErddapServer",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=64, verbose_name="Server Name")),
                (
                    "base_url",
                    models.CharField(
                        max_length=256,
                        verbose_name="ERDDAP API base URL",
                    ),
                ),
                (
                    "contact",
                    models.TextField(
                        blank=True,
                        null=True,
                        verbose_name="Contact information",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="MooringType",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=64, verbose_name="Mooring type")),
            ],
        ),
        migrations.CreateModel(
            name="Platform",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=50, verbose_name="Platform name")),
                (
                    "mooring_site_Desc",
                    models.TextField(verbose_name="Mooring Site Description"),
                ),
                (
                    "nbdc_site_id",
                    models.CharField(blank=True, max_length=100, null=True),
                ),
                (
                    "uscg_light_letter",
                    models.CharField(blank=True, max_length=10, null=True),
                ),
                (
                    "uscg_light_num",
                    models.CharField(blank=True, max_length=16, null=True),
                ),
                ("watch_circle_radius", models.IntegerField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="Program",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=50)),
                ("website", models.TextField()),
            ],
        ),
        migrations.CreateModel(
            name="ProgramAttribution",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("attribution", models.TextField()),
                (
                    "platform",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="deployments.Platform",
                    ),
                ),
                (
                    "program",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="deployments.Program",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="StationType",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=64, verbose_name="Station type")),
            ],
        ),
        migrations.CreateModel(
            name="TimeSeries",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("depth", models.FloatField(default=0)),
                ("start_time", models.DateTimeField()),
                ("end_time", models.DateTimeField(blank=True, null=True)),
                ("erddap_dataset", models.CharField(max_length=256)),
                (
                    "buffer_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="deployments.BufferType",
                    ),
                ),
                (
                    "data_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="deployments.DataType",
                    ),
                ),
                (
                    "erddap_server",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="deployments.ErddapServer",
                    ),
                ),
                (
                    "platform",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="deployments.Platform",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="platform",
            name="programs",
            field=models.ManyToManyField(
                through="deployments.ProgramAttribution",
                to="deployments.Program",
            ),
        ),
        migrations.AddField(
            model_name="erddapserver",
            name="program",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="deployments.Program",
            ),
        ),
        migrations.AddField(
            model_name="deployment",
            name="mooring_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="deployments.MooringType",
            ),
        ),
        migrations.AddField(
            model_name="deployment",
            name="platform",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="deployments.Platform",
            ),
        ),
        migrations.AddField(
            model_name="deployment",
            name="station_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="deployments.StationType",
            ),
        ),
    ]
