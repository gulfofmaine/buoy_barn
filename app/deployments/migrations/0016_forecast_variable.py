# Generated by Django 2.1.2 on 2019-01-07 21:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deployments", "0015_auto_20190107_2120"),
    ]

    operations = [
        migrations.AddField(
            model_name="forecast",
            name="variable",
            field=models.CharField(default="Thgt", max_length=256),
            preserve_default=False,
        ),
    ]
