# Generated by Django 2.1.2 on 2018-12-11 14:53

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('deployments', '0005_auto_20181210_1631'),
    ]

    operations = [
        migrations.AddField(
            model_name='timeseries',
            name='constraints',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, help_text='Extra constratints needed when querying ERDDAP (for example: when datasets have multiple platforms)', null=True, verbose_name='Extra ERDDAP constraints'),
        ),
    ]
