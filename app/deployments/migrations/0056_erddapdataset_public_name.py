# Generated by Django 5.1.3 on 2024-12-04 12:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deployments', '0055_timeseries_extrema_values'),
    ]

    operations = [
        migrations.AddField(
            model_name='erddapdataset',
            name='public_name',
            field=models.CharField(blank=True, help_text='The name of the dataset as it should be displayed in the UI', max_length=256, null=True),
        ),
    ]
