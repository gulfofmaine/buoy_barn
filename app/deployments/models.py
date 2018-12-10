from collections import defaultdict
from datetime import datetime
import logging

from django.contrib.gis.db import models
from erddapy import ERDDAP
import requests

from deployments.utils.erddap_datasets import filter_dataframe, retrieve_dataframe


logger = logging.getLogger(__name__)


class Program(models.Model):
    name = models.CharField(max_length=50)
    website = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name  


class Platform(models.Model):
    name = models.CharField("Platform name", max_length=50)
    mooring_site_Desc = models.TextField("Mooring Site Description")

    programs = models.ManyToManyField(Program, through='ProgramAttribution')

    nbdc_site_id = models.CharField(max_length=100, null=True, blank=True)
    uscg_light_letter = models.CharField(max_length=10, null=True, blank=True)
    uscg_light_num = models.CharField(max_length=16, null=True, blank=True)
    watch_circle_radius = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def current_deployment(self):
        return self.deployment_set.filter(end_time=None).order_by('-start_time').first()

    @property
    def location(self):
        return self.current_deployment.geom

    def group_timeseries_by_erddap_dataset(self):
        datasets = defaultdict(list)

        for ts in self.timeseries_set.filter(end_time=None).select_related('data_type', 'erddap_server'):
            datasets[(ts.erddap_server, ts.erddap_dataset)].append(ts)
        
        return datasets
    
    def latest_erddap_values(self):
        readings = []

        for (server, dataset), timeseries in self.group_timeseries_by_erddap_dataset().items():
            df = filter_dataframe(retrieve_dataframe(server, dataset, timeseries))

            for series in timeseries:
                try:
                    row = df[df['depth'] == series.depth].iloc[-1]
                except IndexError:
                    logger.warning(f'Unable to find position in dataframe for {self.name} - {series.variable}')
                    reading = None
                    time = None
                else:
                    reading = row[series.variable]
                    time = row['time'].strftime('%Y-%m-%dT%H:%M:%SZ')
                readings.append({'value': reading, 
                                'time': time,
                                'depth': series.depth,
                                'data_type': series.data_type.json,
                                'server': series.erddap_server.base_url,
                                'variable': series.variable})
        return readings

    def latest_legacy_readings(self):
        r = requests.get(f'http://neracoos.org/data/json/buoyrecentdata.php?platform={self.name}&mp=no&hb=24&tsdt=all').json()

        readings = {}
        for name in r:
            if 'time_series' in name:
                time = sorted(r[name], key=lambda dt: datetime.strptime(dt + '00', '%Y-%m-%d %H:%M:%S%z'), reverse=True)[0]
                time_series_readings = r[name][time]

                name = name.split('-')[1]

                readings[name] = {'readings': [dict(**reading, time=time) for reading in time_series_readings]}
        
        return readings
    

class ProgramAttribution(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE)
    attribution = models.TextField()


class MooringType(models.Model):
    name = models.CharField("Mooring type", max_length=64)

    def __str__(self):
        return self.name


class StationType(models.Model):
    name = models.CharField('Station type', max_length=64)

    def __str__(self):
        return self.name


class Deployment(models.Model):
    deployment_name = models.CharField('Deployment platform name', max_length=50)

    platform = models.ForeignKey(Platform, on_delete=models.CASCADE)

    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    geom = models.PointField('Location')
    magnetic_variation = models.FloatField()
    water_depth = models.FloatField()
    
    mooring_type = models.ForeignKey(MooringType, on_delete=models.CASCADE, null=True, blank=True)
    mooring_site_id = models.TextField()

    station_type = models.ForeignKey(StationType, on_delete=models.CASCADE)

    def __str__(self):
        if self.end_time:
            return f'{self.platform.name}: {self.deployment_name} - ({self.start_time.date()} - {self.end_time.date()} - {self.start_time - self.end_time})'
        return f'{self.platform.name}: {self.deployment_name} - (launched: {self.start_time.date()})'


class DataType(models.Model):
    standard_name = models.CharField(max_length=128)
    short_name = models.CharField(max_length=16)
    long_name = models.CharField(max_length=128)
    units = models.CharField(max_length=64)

    # preffered_unit = models.CharField(max_length=16)

    def __str__(self):
        return f'{self.standard_name} - {self.long_name} ({self.units})'
    
    @property
    def json(self):
        return {
            'standard_name': self.standard_name,
            'short_name': self.short_name,
            'long_name': self.long_name,
            'units': self.units
        }


class BufferType(models.Model):
    name = models.CharField('Buffer type', max_length=64)

    def __str__(self):
        return self.name


class ErddapServer(models.Model):
    name = models.CharField('Server Name', max_length=64, null=True)
    base_url = models.CharField('ERDDAP API base URL', max_length=256)
    program = models.ForeignKey(Program, on_delete=models.CASCADE, null=True, blank=True)
    contact = models.TextField('Contact information', null=True, blank=True)

    def __str__(self):
        if self.name:
            return self.name
        return self.base_url
    
    def connection(self):
        return ERDDAP(self.base_url)


class TimeSeries(models.Model):
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE)
    data_type = models.ForeignKey(DataType, on_delete=models.CASCADE)
    variable = models.CharField(max_length=256)

    depth = models.FloatField(default=0)

    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    buffer_type = models.ForeignKey(BufferType, on_delete=models.CASCADE)
    erddap_dataset = models.CharField(max_length=256, null=True, blank=True)
    erddap_server = models.ForeignKey(ErddapServer, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f'{self.platform.name} - {self.data_type.standard_name} - {self.depth}'
