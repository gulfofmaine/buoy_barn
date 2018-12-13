from django.test import TestCase

from deployments.models import Deployment, Program, Platform, ProgramAttribution, StationType


class ProgramTestCase(TestCase):
    def setUp(self):
        self.program = Program.objects.create(
            name="NERACOOS", website="http://neracoos.org"
        )

    def test_program_attributes(self):
        neracoos = Program.objects.get(name="NERACOOS")

        self.assertEquals(neracoos.name, "NERACOOS")
        self.assertEquals(neracoos.website, "http://neracoos.org")

    def test_program_json(self):
        neracoos = Program.objects.get(name="NERACOOS")

        self.assertIn("name", neracoos.json)
        self.assertIn("website", neracoos.json)

        self.assertEquals(neracoos.json["name"], "NERACOOS")
        self.assertIn("http://neracoos.org", neracoos.json["website"])


class PlatformTestCase(TestCase):
    def setUp(self):
        self.platform = Platform.objects.create(
            name="N01",
            mooring_site_desc="Northeast Channel",
            geom="SRID=4326;POINT(-65.9 42.34)",
        )

    def test_platform_attributes(self):
        n01 = Platform.objects.get(name="N01")

        self.assertEquals(self.platform.name, n01.name)

    def test_location(self):
        n01 = Platform.objects.get(name="N01")

        self.assertIsNotNone(n01.location)
        self.assertEquals(n01.location.x, -65.9)
        self.assertEquals(n01.location.y, 42.34)
        self.assertEquals(n01.location.srid, 4326)


class ProgramAttributionTestCase(TestCase):
    fixtures = ["programs", "platforms"]

    def setUp(self):
        self.platform = Platform.objects.get(name="N01")

        self.neracoos = Program.objects.get(name="NERACOOS")

        self.attribution = ProgramAttribution.objects.create(
            program=self.neracoos,
            platform=self.platform,
            attribution="Managed by NERACOOS",
        )

    def test_attribution_str(self):
        attribution_string = str(self.attribution)

        self.assertIn("N01", attribution_string)
        self.assertIn("NERACOOS", attribution_string)

    def test_attribution_json(self):
        attribution = ProgramAttribution.objects.get(
            program=self.neracoos, platform=self.platform
        )

        self.assertIn("program", attribution.json)
        self.assertEquals("NERACOOS", attribution.json["program"]["name"])

        self.assertIn("attribution", attribution.json)
        self.assertIn("Managed", attribution.json["attribution"])


class DeploymentTestCase(TestCase):
    fixtures = ["platforms"]

    def setUp(self):
        self.platform = Platform.objects.get(name="A01")
        self.station = StationType.objects.get(name='Surface Mooring')

        self.shared_deployment_kwargs = {
            'platform': self.platform,
            'geom': "SRID=4326;POINT(-70.56 42.53)",
            'water_depth': 65,
            'magnetic_variation': -14.8,
            'station_type': self.station
        }

        self.deployment = Deployment.objects.create(
            deployment_name="A0140",
            start_time="2018-09-28 07:00:00-04",
            mooring_site_id='A0140',
            **self.shared_deployment_kwargs
        )

        self.old_deployment = Deployment.objects.create(
            deployment_name='A0139',
            start_time='2018-07-10 16:00:00-04',
            end_time='2018-09-27 17:00:00-04',
            mooring_site_id='A0139',
            **self.shared_deployment_kwargs
        )
    
    def test_platform_can_get_current_deployment(self):
        deployment = self.platform.current_deployment

        self.assertIsNotNone(deployment)
        self.assertIsNone(deployment.end_time)

    def test_platform_deployment_location(self):
        a01 = Platform.objects.get(name='A01')

        self.assertIsNotNone(a01.location)
        self.assertEquals(a01.location.x, -70.56)
        self.assertEquals(a01.location.y, 42.53)
        self.assertEquals(a01.location.srid, 4326)
    
    def test_deployment_str_with_no_end(self):
        deployment_str = str(Deployment.objects.get(deployment_name='A0140'))

        self.assertIn('A01:', deployment_str)
        self.assertIn('A0140', deployment_str)
        self.assertIn('launched', deployment_str)
        self.assertIn('2018-09-28', deployment_str)

    def test_deployment_str_with_end(self):
        deployment_str = str(Deployment.objects.get(deployment_name='A0139'))

        self.assertIn('A01:', deployment_str)
        self.assertIn('A0139', deployment_str)
        self.assertIn('2018-07-10', deployment_str)
        self.assertIn('2018-09-27', deployment_str)
        self.assertIn('80 days', deployment_str)
