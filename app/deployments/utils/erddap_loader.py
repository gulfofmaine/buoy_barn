import logging
from datetime import datetime, timedelta

import pandas as pd
from erddapy import ERDDAP
from requests.exceptions import HTTPError

from ..models import (
    BufferType,
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    TimeSeries,
)

logger = logging.getLogger(__name__)


def convert_time(time: str) -> datetime:
    """Convert's from ERDDAP time style to python"""
    return datetime.fromisoformat(time.replace("Z", ""))


def add_timeseries(platform: Platform, server: str, dataset: str, constraints):  # noqa: PLR0912,PLR0915
    """Add datatypes for a new dataset to a platform.
    See instructions in Readme.md
    """
    e = ERDDAP(server)

    info = pd.read_csv(e.get_info_url(dataset, response="csv"))
    info_vars = info[info["Row Type"] == "variable"]

    logger.info(f"Opened dataset from ERDDAP and found variables: {''.join(info_vars)}")

    variables = [
        var
        for var in info_vars["Variable Name"]
        if var
        not in [
            "time",
            "station",
            "mooring_site_desc",
            "longitude",
            "latitude",
            "depth",
        ]
        and "_qc" not in var
    ]

    # extract times
    start_time = convert_time(
        info[info["Attribute Name"] == "time_coverage_start"]["Value"].to_numpy()[0],
    )
    end_time = convert_time(
        info[info["Attribute Name"] == "time_coverage_end"]["Value"].to_numpy()[0],
    )
    yesterday = datetime.utcnow() - timedelta(hours=24)
    if end_time > yesterday:
        end_time = None

    # get depths
    e.dataset_id = dataset
    e.response = "nc"
    e.variables = variables
    e.protocol = "tabledap"
    e.constraints = constraints.copy()
    e.constraints["time>="] = yesterday

    try:
        ds = e.to_xarray()
    except HTTPError:
        logger.error(
            "Either the dataset was invalid, the server was down, "
            "or the dataset has not been updated in the last day",
        )
        return

    try:
        buffer = BufferType.objects.get(name=ds.buffer_type)
    except BufferType.DoesNotExist:
        logger.info(f"Searched for buffer type does not exist: {ds.buffer_type}")
        return
    except AttributeError:
        logger.info(f"{dataset} does not have a defined buffer_type")
        buffer = False

    erddap_server = ErddapServer.objects.get(base_url=server)
    erddap_dataset, _ = ErddapDataset.objects.get_or_create(
        name=dataset,
        server=erddap_server,
    )

    for var in ds.variables:
        if var not in [
            "time",
            "depth",
            "time_modified",
            "time_created",
            "water_depth",
            "longitude",
            "latitude",
            "mooring_side_desc",
        ]:
            data_array = ds[var]

            try:
                try:
                    data_type = DataType.objects.get(
                        standard_name=data_array.standard_name,
                    )
                except AttributeError:
                    try:
                        data_type = DataType.objects.get(long_name=data_array.long_name)
                    except AttributeError:
                        data_type = DataType.objects.filter(
                            short_name=data_array.short_name,
                        ).first()

            except DataType.DoesNotExist:
                if all(attr in dir(data_array) for attr in ["standard_name", "long_name", "units"]):
                    data_type = DataType(
                        standard_name=data_array.standard_name,
                        long_name=data_array.long_name,
                        # short_name=data_array.short_name,
                        units=data_array.units,
                    )
                    try:
                        data_type.short_name = data_array.short_name
                    except AttributeError:
                        logger.info(f"{var} does not have a short name")
                    data_type.save()

                else:
                    logger.warning(f"Unable to load or create datatype for {var}")

            finally:
                try:
                    if data_type:
                        time_series = TimeSeries(
                            platform=platform,
                            variable=var,
                            data_type=data_type,
                            start_time=start_time,
                            end_time=end_time,
                            constraints=constraints,
                            dataset=erddap_dataset,
                        )
                        if buffer:
                            time_series.buffer_type = buffer

                        time_series.save()
                except UnboundLocalError:
                    logger.warning(f"No datatype for {var}")
        data_type = None
