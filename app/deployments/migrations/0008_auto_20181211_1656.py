# Generated by Django 2.1.2 on 2018-12-11 16:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deployments", "0007_auto_20181211_1635"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datatype",
            name="short_name",
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
    ]
