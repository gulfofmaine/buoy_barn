"""list_display callables shared by more than one admin, so neither owns the other's dependency."""

from datetime import timedelta

from django.contrib.gis import admin
from django.utils import timezone
from django.utils.html import format_html

from ..models import ErddapDataset, Platform


@admin.display(description="Timeseries status")
def timeseries_status(obj: ErddapDataset | Platform):
    """Shows an inline display of timeseries status on a dataset or platform admin"""
    now = timezone.now()
    hour_ago = now - timedelta(hours=24)
    day_ago = now - timedelta(days=1)

    active_timeseries = []
    inactive_timeseries = []

    for ts in obj.timeseries_set.all():
        if ts.active and ts.value_time is not None:
            try:
                if ts.end_time < now:
                    inactive_timeseries.append(ts)
                    continue
            except TypeError:
                pass
            active_timeseries.append(ts)
        else:
            inactive_timeseries.append(ts)

    hour_delayed = [ts for ts in active_timeseries if ts.value_time < hour_ago]
    day_delayed = [ts for ts in active_timeseries if ts.value_time < day_ago]

    inactive_color = "gray" if len(inactive_timeseries) == 0 else "black"

    active_title = "\n".join(
        f"{ts} ({ts.value} @ {ts.value_time:%Y-%m-%d %H:%M})"
        if ts.value_time
        else f"{ts} (Not refreshed)"
        for ts in active_timeseries
    )
    inactive_title = "\n".join(
        f"{ts} ({ts.value} @ {ts.value_time:%Y-%m-%d %H:%M})"
        if ts.value_time
        else f"{ts} (Not refreshed)"
        for ts in inactive_timeseries
    )

    if len(day_delayed) > 0:
        return format_html(
            (
                "<span style='color: {};' title='{}'>{}</span>"
                " {} / {} "
                "<span style='color: {};' title='{}'>({} inactive)</span>"
            ),
            "red",
            active_title,
            "Delayed by at least a day",
            len(day_delayed),
            len(active_timeseries),
            inactive_color,
            inactive_title,
            len(inactive_timeseries),
        )
    elif len(hour_delayed) > 0:
        return format_html(
            (
                "<span style='color: {};' title='{}'>"
                "{} / {} "
                "<span style='color: {};' title='{}'>({} inactive)</span>"
            ),
            "yellow",
            active_title,
            "Delayed by at least an hour",
            len(hour_delayed),
            len(active_timeseries),
            inactive_color,
            inactive_title,
            len(inactive_timeseries),
        )

    return format_html(
        (
            "<span style='color: {};' title='{}'>{}</span>"
            " {} / {} "
            "<span style='color: {};' title='{}'>({} inactive)</span>"
        ),
        "green",
        active_title,
        "Active",
        len(active_timeseries),
        len(active_timeseries),
        inactive_color,
        inactive_title,
        len(inactive_timeseries),
    )
