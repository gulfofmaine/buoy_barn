# Generated by Django 5.0.1 on 2024-01-11 14:47

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("deployments", "0047_alter_floodlevel_level_other_platformlinks"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="PlatformLinks",
            new_name="PlatformLink",
        ),
    ]