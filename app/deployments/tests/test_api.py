import geojson
from rest_framework.test import APITestCase

from deployments.models import Platform, TimeSeries, ErddapServer, DataType, BufferType


class BuoyBarnAPITestCase(APITestCase):
    fixtures = ['platforms', 'erddapservers']

    def setUp(self):
        self.platform = Platform.objects.get(name='N01')
        self.erddap = ErddapServer.objects.get(base_url='http://www.neracoos.org/erddap')

        # self.conductivity = DataType.objects.get(standard_name='sea_water_electrical_conductivity')
        self.salinity = DataType.objects.get(standard_name="sea_water_salinity")
        self.water_temp = DataType.objects.get(standard_name='sea_water_temperature')
        self.current_direction = DataType.objects.get(standard_name='direction_of_sea_water_velocity')

        self.buffer_type = BufferType.objects.get(name='sbe37')

        # two time series from the same dataset and constraints
        self.ts1 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.salinity,
            variable='salinity',
            constraints={"depth=": 100.0},
            depth=1,
            start_time='2004-06-03 21:00:00+00',
            end_time=None,
            buffer_type=self.buffer_type,
            erddap_dataset='N01_sbe37_all',
            erddap_server=self.erddap
        )
        self.ts2 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.water_temp,
            variable='temperature',
            constraints={"depth=": 100.0},
            depth=1,
            start_time='2004-06-03 21:00:00+00',
            end_time=None,
            buffer_type=self.buffer_type,
            erddap_dataset='N01_sbe37_all',
            erddap_server=self.erddap
        )

        # one with the same dataset but a different constraint
        self.ts3 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.water_temp,
            variable='temperature',
            constraints={"depth=": 1.0},
            depth=1,
            start_time='2004-06-03 21:00:00+00',
            end_time=None,
            buffer_type=self.buffer_type,
            erddap_dataset='N01_sbe37_all',
            erddap_server=self.erddap
        )

        # one with a different dataset
        self.ts4 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.current_direction,
            variable='current_direction',
            constraints={"depth=": 2.0},
            depth=1,
            start_time='2004-06-03 21:00:00+00',
            end_time=None,
            buffer_type=None,
            erddap_dataset='N01_aanderaa_all',
            erddap_server=self.erddap
        )

        # one that has an end_time so it should not be offered
        self.ts5 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.water_temp,
            variable='temperature',
            constraints={"depth=": 100.0},
            depth=1,
            start_time='2004-06-03 21:00:00+00',
            end_time='2007-06-03 21:00:00+00',
            buffer_type=self.buffer_type,
            erddap_dataset='N01_sbe37_all',
            erddap_server=self.erddap
        )

    def test_platform_detail_with_no_time_series(self):
        response = self.client.get('/api/platforms/A01/', format='json')

        for key in ('id', 'type', 'geometry', 'properties'):
            self.assertIn(key, response.data, msg=f'{key} not in top level of response')

        geo = geojson.loads(response.content)

        self.assertTrue(geo.is_valid)
        self.assertEqual('Feature', geo['type'])

        for key in ('readings', 'attribution', 'mooring_site_desc', 'nbdc_site_id', 'uscg_light_letter', 'uscg_light_num', 'watch_circle_radius', 'programs'):
            self.assertIn(key, geo['properties'], msg=f'{key} is not in feature properties')
        self.assertNotIn('geom', geo['properties'])
        
        self.assertEqual(0, len(geo['properties']['readings']))

    def test_platform_detail_with_time_series(self):
        response = self.client.get('/api/platforms/N01/', format='json')

        for key in ('id', 'type', 'geometry', 'properties'):
            self.assertIn(key, response.data, msg=f'{key} not in top level of response')

        geo = geojson.loads(response.content)

        self.assertTrue(geo.is_valid)
        self.assertEqual('Feature', geo['type'])

        for key in ('readings', 'attribution', 'mooring_site_desc', 'nbdc_site_id', 'uscg_light_letter', 'uscg_light_num', 'watch_circle_radius', 'programs'):
            self.assertIn(key, geo['properties'], msg=f'{key} is not in feature properties')
        self.assertNotIn('geom', geo['properties'])

        self.assertEqual(4, len(geo['properties']['readings']))

        for reading in geo['properties']['readings']:
            for key in ('value', 'time', 'depth', 'data_type', 'server', 'variable', 'constraints', 'dataset'):
                self.assertIn(key, reading, msg=f'{key} not found in reading: {reading}')

            self.assertIsInstance(reading['value'], float, msg=f"reading['value']: {reading} is not a float")
            self.assertEqual(reading['server'], "http://www.neracoos.org/erddap")
            self.assertIn(reading['variable'], ('salinity', 'temperature', 'current_direction'))
            self.assertIn(reading['dataset'], ('N01_sbe37_all', 'N01_aanderaa_all'))

            for key in ('standard_name', 'short_name', 'long_name', 'units'):
                self.assertIn(key, reading['data_type'])

    def test_platform_list(self):
        response = self.client.get('/api/platforms/', format='json')

        geo = geojson.loads(response.content)

        self.assertTrue(geo.is_valid)
        self.assertEqual('FeatureCollection', geo['type'])

        self.assertEqual(13, len(geo['features']))
