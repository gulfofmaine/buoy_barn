from datetime import datetime, timedelta
import logging

import pandas as pd
from erddapy import ERDDAP
from requests.exceptions import HTTPError

from ..models import Platform, TimeSeries, ErddapServer, DataType, BufferType


logger = logging.getLogger(__name__)


def convert_time(time: str) -> datetime:
    "Convert's from ERDDAP time style to python"
    return datetime.fromisoformat(time.replace('Z', ''))


def add_timeseries(platform: Platform, server: str, dataset: str, constraints):
    e = ERDDAP(server)

    info = pd.read_csv(e.get_info_url(dataset, response='csv'))
    info_vars = info[info['Row Type'] == 'variable']
    variables = [var for var in info_vars['Variable Name']
                 if var not in ['time', 'station', 'mooring_site_desc', 'longitude', 'latitude', 'depth']
                 and  '_qc' not in var]
    
    # extract times
    start_time = convert_time(info[info['Attribute Name'] == 'time_coverage_start']['Value'].get_values()[0])
    end_time = convert_time(info[info['Attribute Name'] == 'time_coverage_end']['Value'].get_values()[0])
    yesterday = datetime.utcnow() - timedelta(hours=24)
    if end_time > yesterday:
        end_time = None

    # get depths
    e.dataset_id = dataset
    e.response = 'nc'
    e.variables = variables
    e.protocol = 'tabledap'
    e.constraints = constraints.copy()
    e.constraints['time>='] = yesterday

    try:
        ds = e.to_xarray()
    except HTTPError:
        logger.error('Either the dataset was invalid, the server was down, or the dataset has not been updated in the last day')
        return

    try:
        buffer = BufferType.objects.get(name=ds.buffer_type)
    except BufferType.DoesNotExist:
        logger.info(f'Searched for buffer type does not exist: {ds.buffer_type}')
        return
    except AttributeError:
        logger.info(f"{dataset} does not have a defined buffer_type")
        buffer = False

    erddap_server = ErddapServer.objects.get(base_url=server)

    for var in ds.variables:
        if var not in ['time', 'depth', 'time_modified', 'time_created']:
            data_array = ds[var]

            try:
                try:
                    data_type = DataType.objects.get(standard_name=data_array.standard_name)
                except AttributeError:
                    try:
                        data_type = DataType.objects.get(long_name=data_array.long_name)
                    except AttributeError:
                        data_type = DataType.objects.filter(short_name=data_array.short_name).first()

            except DataType.DoesNotExist:
                if all(attr in dir(data_array) for attr in ['standard_name', 'long_name', 'units']):
                    data_type = DataType(standard_name=data_array.standard_name,
                                        long_name=data_array.long_name,
                                        # short_name=data_array.short_name,
                                        units=data_array.units)
                    try:
                        data_type.short_name = data_array.short_name
                    except AttributeError:
                        logger.info(f'{var} does not have a short name')
                    data_type.save()


                else:
                    logger.warning(f'Unable to load or create datatype for {var}')

            finally:
                if data_type:
                    time_series = TimeSeries(
                        platform=platform,
                        variable=var,
                        data_type=data_type,
                        start_time=start_time,
                        end_time=end_time,
                        constraints=constraints,
                        erddap_dataset=dataset,
                        erddap_server=erddap_server
                    )
                    if buffer:
                        time_series.buffer_type=buffer

                    time_series.save()
        data_type = None
