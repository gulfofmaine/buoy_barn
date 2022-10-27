from datetime import timedelta

from prefect import Flow
from prefect.schedules import Schedule
from prefect.schedules.clocks import CronClock
from prefect.storage.local import Local

from deployments.flows.refresh_tasks import (
    not_recently_refreshed_datasets,
    refresh_dataset,
    refreshed_datasets_status,
)

# Task is scheduled to hour,
# so we should check something slightly less than that
NOT_RECENTLY = timedelta(minutes=45)

flow_name = "hourly-default-dataset-refresh"

with Flow(flow_name) as flow:
    old_datasets = not_recently_refreshed_datasets(NOT_RECENTLY)
    refreshed_dataset_ids = refresh_dataset.map(old_datasets)
    refreshed_datasets_status(refreshed_dataset_ids)

# flow should be stored as script so that `django.setup()` gets called appropriately
flow.storage = Local(
    path="deployments.flows.default_dataset_refresh",
    stored_as_script=True,
)

schedule = Schedule(clocks=[CronClock("0 */1 * * *")])
