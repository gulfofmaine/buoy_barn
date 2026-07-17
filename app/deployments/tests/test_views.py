import json
from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from rest_framework.test import APITestCase

from .vcr import my_vcr


@pytest.mark.django_db
class ProxyViewTestCase(APITestCase):
    fixtures = ["erddapservers"]

    @my_vcr.use_cassette("proxy_view.yaml")
    def test_proxy_view(self):
        response = self.client.get(
            (
                "http://localhost:8080/api/servers/1/proxy/tabledap/M01_met_all.json"
                "?time%2Cair_temperature%26air_temperature_qc%3D0%26"
                "time%3E%3D%222021-03-01T15%3A25%3A00.000Z%22"
            ),
            format="json",
        )
        data = json.loads(response.content)

        assert "table" in data

        for key in ("columnNames", "columnTypes", "columnUnits", "rows"):
            assert key in data["table"]

    def test_proxy_view_with_content_length_header(self):
        upstream_response = httpx.Response(
            200,
            content=b'{"table": {}}',
            request=httpx.Request("GET", "http://localhost:8080/tabledap/M01_met_all.json"),
        )
        assert "content-length" in upstream_response.headers

        with patch(
            "deployments.views._proxy_http_client.get",
            new=AsyncMock(return_value=upstream_response),
        ):
            response = self.client.get(
                "http://localhost:8080/api/servers/1/proxy/tabledap/M01_met_all.json",
                format="json",
            )

        assert response.status_code == HTTPStatus.OK
        assert json.loads(response.content) == {"table": {}}
