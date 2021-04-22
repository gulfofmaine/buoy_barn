import json

import pytest

from rest_framework.test import APITestCase

from .vcr import my_vcr


@pytest.mark.django_db
class ProxyViewTestCase(APITestCase):
    fixtures = ["erddapservers"]

    @my_vcr.use_cassette("proxy_view.yaml")
    def test_proxy_view(self):
        response = self.client.get(
            "http://localhost:8080/api/servers/1/proxy/tabledap/M01_met_all.json?time%2Cair_temperature%26air_temperature_qc%3D0%26time%3E%3D%222021-03-01T15%3A25%3A00.000Z%22",
            format="json",
        )
        data = json.loads(b"".join(response.streaming_content))

        assert "table" in data

        for key in ("columnNames", "columnTypes", "columnUnits", "rows"):
            assert key in data["table"]
