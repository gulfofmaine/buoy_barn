import os
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from slack_sdk import WebClient

from deployments.models import TimeSeries
from deployments.utils.healthchecks import ping_healthcheck

#: Metric label for the weekly monitor. Give it a weekly schedule and grace period on the
#: Healthchecks.io side so a beat that stops firing this task alerts on absence.
WEEKLY_MONITOR = "weekly_old_timeseries"


@shared_task
def more_thank_a_week_old():
    healthcheck_url = os.environ.get("WEEKLY_OLD_TIMESERIES_HEALTHCHECK_URL")
    ping_healthcheck(healthcheck_url, WEEKLY_MONITOR, start=True)

    # timezone.now() rather than datetime.now(): value_time is an aware DateTimeField and
    # USE_TZ is on, so a naive comparison raises a RuntimeWarning and is only correct by
    # accident of TIME_ZONE being UTC.
    week_ago = timezone.now() - timedelta(days=7)

    ts_week_ago = TimeSeries.objects.filter(
        value_time__lt=week_ago,
        active=True,
    )

    platforms = {}

    for ts in ts_week_ago.iterator(chunk_size=100):
        platform = platforms.get(ts.platform.name, [])

        platform.append(f"{ts} @ {ts.value_time.strftime('%Y-%m-%d %H:%M')}")
        platforms[ts.platform.name] = platform

    if platforms:
        message = "Timeseries that are more than a week out of date in Buoy Barn:\n"
        for platform, series in platforms.items():
            message += f"- *{platform}*\n"

            for ts in series:
                message += f"    - {ts}\n"

        message += (
            "\nIt may be worth going into the admin and running the "
            "`Disable timeseries that are more than a week out of date` "
            "Platform action to reduce errors."
        )

        if settings.SLACK_API_TOKEN and settings.SLACK_API_CHANNEL:
            client = WebClient(token=settings.SLACK_API_TOKEN)

            client.chat_postMessage(
                channel=f"#{settings.SLACK_API_CHANNEL}",
                text=message,
            )

    # Outside the `if platforms:` block: finding nothing stale is a successful run, and the
    # monitor needs to hear about it or it would alert every quiet week.
    ping_healthcheck(healthcheck_url, WEEKLY_MONITOR)
