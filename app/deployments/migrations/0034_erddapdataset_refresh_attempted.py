# Generated by Django 3.1.7 on 2021-03-15 23:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deployments', '0033_auto_20210314_0228'),
    ]

    operations = [
        migrations.AddField(
            model_name='erddapdataset',
            name='refresh_attempted',
            field=models.DateTimeField(blank=True, help_text='Last time that Buoy Barn attempted to refresh this dataset', null=True),
        ),
    ]