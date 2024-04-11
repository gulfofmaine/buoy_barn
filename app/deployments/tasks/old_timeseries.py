import logging
from datetime import datetime, timedelta

from django.conf import settings
from celery import shared_task
from slack_sdk import WebClient

from deployments.models import Platform, TimeSeries

@shared_task
def more_thank_a_week_old():
    week_ago = datetime.now() - timedelta(days=7)

    ts_week_ago = TimeSeries.objects.filter(
        value_time__lt=week_ago,
        active=True
    )

    platforms = {}

    for ts in ts_week_ago.iterator():
        platform = platforms.get(ts.platform.name, [])

        platform.append(f"{ts} @ {ts.value_time.strftime('%Y-%m-%d %H:%M')}")
        platforms[ts.platform.name] = platform
    
    if platforms:
        message = "Timeseries that are more than a week out of date in Buoy Barn:\n"
        for platform in platforms:
            message += f"- *{platform}*\n"

            for ts in platforms[platform]:
                message += f"    - {ts}\n"

        message += "\nIt may be worth going into the admin and running the "
        message += "`Disable timeseries that are more than a week out of date` Platform action to reduce errors."

        if settings.SLACK_API_TOKEN and settings.SLACK_API_CHANNEL:
            client = WebClient(token=settings.SLACK_API_TOKEN)

            response = client.chat_postMessage(
                channel=f"#{settings.SLACK_API_CHANNEL}",
                text=message
            )

