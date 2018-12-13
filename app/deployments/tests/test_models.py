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

