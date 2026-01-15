"""Tests for the erddap_mqtt management command."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from deployments.management.commands.erddap_mqtt import Command, get_client_id
from deployments.models import ErddapDataset, ErddapServer


class TestGetClientId:
    """Tests for the get_client_id function."""

    def test_returns_string(self):
        """get_client_id should return a string."""
        client_id = get_client_id()
        assert isinstance(client_id, str)

    def test_has_expected_prefix(self):
        """Client ID should have the expected prefix."""
        client_id = get_client_id()
        assert client_id.startswith("buoy-barn-mqtt-subscriber-")

    def test_is_deterministic(self):
        """Client ID should be deterministic (based on MAC address)."""
        client_id_1 = get_client_id()
        client_id_2 = get_client_id()
        assert client_id_1 == client_id_2


@pytest.mark.django_db
class TestErddapMqttCommand:
    """Tests for the erddap_mqtt management command."""

    @pytest.fixture
    def erddap_server(self):
        """Create an ERDDAP server for testing."""
        return ErddapServer.objects.create(
            name="test-server",
            base_url="http://test.erddap.server/erddap",
            mqtt_broker="mqtt.test.server",
            mqtt_port=1883,
            mqtt_username="test_user",
            mqtt_password="test_password",
        )

    @pytest.fixture
    def erddap_server_no_mqtt(self):
        """Create an ERDDAP server without MQTT configuration."""
        return ErddapServer.objects.create(
            name="no-mqtt-server",
            base_url="http://test.erddap.server/erddap",
        )

    @pytest.fixture
    def erddap_server_no_credentials(self):
        """Create an ERDDAP server with MQTT broker but no credentials."""
        return ErddapServer.objects.create(
            name="no-creds-server",
            base_url="http://test.erddap.server/erddap",
            mqtt_broker="mqtt.test.server",
        )

    @pytest.fixture
    def erddap_dataset(self, erddap_server):
        """Create an ERDDAP dataset for testing."""
        return ErddapDataset.objects.create(
            name="test_dataset",
            server=erddap_server,
        )

    @pytest.fixture
    def command(self):
        """Create a Command instance for testing."""
        return Command()

    def test_server_not_found(self):
        """Command should raise error when server slug doesn't exist."""
        with pytest.raises(CommandError, match="ERDDAP server with slug 'nonexistent' not found"):
            call_command("erddap_mqtt", "nonexistent")

    def test_no_mqtt_broker_configured(self, erddap_server_no_mqtt):
        """Command should raise error when server has no MQTT broker configured."""
        with pytest.raises(CommandError, match="No MQTT broker configured"):
            call_command("erddap_mqtt", "no-mqtt-server")

    def test_no_mqtt_credentials_configured(self, erddap_server_no_credentials):
        """Command should raise error when server has no MQTT credentials."""
        with pytest.raises(CommandError, match="No MQTT credentials configured"):
            call_command("erddap_mqtt", "no-creds-server")

    def test_get_erddap_server_success(self, command, erddap_server):
        """get_erddap_server should return the server when valid."""
        result = command.get_erddap_server("test-server")
        assert result == erddap_server

    def test_get_erddap_server_not_found(self, command):
        """get_erddap_server should raise CommandError when server not found."""
        with pytest.raises(CommandError, match="ERDDAP server with slug 'nonexistent' not found"):
            command.get_erddap_server("nonexistent")

    def test_get_erddap_server_no_broker(self, command, erddap_server_no_mqtt):
        """get_erddap_server should raise CommandError when no MQTT broker configured."""
        with pytest.raises(CommandError, match="No MQTT broker configured"):
            command.get_erddap_server("no-mqtt-server")

    def test_get_erddap_server_no_credentials(self, command, erddap_server_no_credentials):
        """get_erddap_server should raise CommandError when no credentials configured."""
        with pytest.raises(CommandError, match="No MQTT credentials configured"):
            command.get_erddap_server("no-creds-server")


@pytest.mark.django_db
class TestOnConnectCallback:
    """Tests for the on_connect callback."""

    @pytest.fixture
    def erddap_server(self):
        """Create an ERDDAP server for testing."""
        return ErddapServer.objects.create(
            name="test-server",
            base_url="http://test.erddap.server/erddap",
            mqtt_broker="mqtt.test.server",
            mqtt_port=1883,
            mqtt_username="test_user",
            mqtt_password="test_password",
        )

    def test_on_connect_subscribes_to_change_topics(self, erddap_server):
        """on_connect callback should subscribe to change/# topics."""
        command = Command()
        command.stdout = StringIO()
        command.style = MagicMock()
        command.style.SUCCESS = lambda x: x

        on_connect = command.create_on_connect_callback(erddap_server)

        mock_client = MagicMock()
        on_connect(mock_client, None, None, None, None)

        mock_client.subscribe.assert_called_once_with("change/#")

    def test_on_connect_writes_status_messages(self, erddap_server):
        """on_connect callback should write status messages to stdout."""
        command = Command()
        command.stdout = StringIO()
        command.style = MagicMock()
        command.style.SUCCESS = lambda x: x

        on_connect = command.create_on_connect_callback(erddap_server)

        mock_client = MagicMock()
        on_connect(mock_client, None, None, None, None)

        output = command.stdout.getvalue()
        assert "Connected to MQTT broker" in output
        assert "mqtt.test.server" in output


@pytest.mark.django_db
class TestOnMessageCallback:
    """Tests for the on_message callback."""

    @pytest.fixture
    def erddap_server(self):
        """Create an ERDDAP server for testing."""
        return ErddapServer.objects.create(
            name="test-server",
            base_url="http://test.erddap.server/erddap",
            mqtt_broker="mqtt.test.server",
            mqtt_port=1883,
            mqtt_username="test_user",
            mqtt_password="test_password",
        )

    @pytest.fixture
    def erddap_dataset(self, erddap_server):
        """Create an ERDDAP dataset for testing."""
        return ErddapDataset.objects.create(
            name="test_dataset",
            server=erddap_server,
        )

    def test_on_message_extracts_dataset_name(self, erddap_server, erddap_dataset):
        """on_message should extract dataset name from topic."""
        command = Command()
        command.stdout = StringIO()
        command.style = MagicMock()
        command.style.SUCCESS = lambda x: x
        command.style.NOTICE = lambda x: x

        on_message = command.create_on_message_callback(erddap_server)

        mock_msg = MagicMock()
        mock_msg.topic = "change/test_dataset"

        with patch("deployments.management.commands.erddap_mqtt.single_refresh_dataset") as _:
            on_message(None, None, mock_msg)

        output = command.stdout.getvalue()
        assert "test_dataset" in output

    @patch("deployments.management.commands.erddap_mqtt.single_refresh_dataset")
    def test_on_message_schedules_refresh_for_known_dataset(
        self,
        mock_refresh,
        erddap_server,
        erddap_dataset,
    ):
        """on_message should schedule a refresh for known datasets."""
        command = Command()
        command.stdout = StringIO()
        command.style = MagicMock()
        command.style.SUCCESS = lambda x: x

        on_message = command.create_on_message_callback(erddap_server)

        mock_msg = MagicMock()
        mock_msg.topic = "change/test_dataset"

        on_message(None, None, mock_msg)

        mock_refresh.delay.assert_called_once_with(erddap_dataset.id)

    @patch("deployments.management.commands.erddap_mqtt.single_refresh_dataset")
    def test_on_message_ignores_unknown_dataset(self, mock_refresh, erddap_server):
        """on_message should not schedule refresh for unknown datasets."""
        command = Command()
        command.stdout = StringIO()
        command.style = MagicMock()
        command.style.SUCCESS = lambda x: x
        command.style.NOTICE = lambda x: x

        on_message = command.create_on_message_callback(erddap_server)

        mock_msg = MagicMock()
        mock_msg.topic = "change/unknown_dataset"

        on_message(None, None, mock_msg)

        mock_refresh.delay.assert_not_called()

    def test_on_message_writes_notice_for_unknown_dataset(self, erddap_server):
        """on_message should write notice for unknown datasets."""
        command = Command()
        command.stdout = StringIO()
        command.style = MagicMock()
        command.style.NOTICE = lambda x: f"[NOTICE] {x}"
        command.style.SUCCESS = lambda x: x

        on_message = command.create_on_message_callback(erddap_server)

        mock_msg = MagicMock()
        mock_msg.topic = "change/unknown_dataset"

        with patch("deployments.management.commands.erddap_mqtt.single_refresh_dataset"):
            on_message(None, None, mock_msg)

        output = command.stdout.getvalue()
        assert "No dataset found" in output
        assert "unknown_dataset" in output

    @patch("deployments.management.commands.erddap_mqtt.single_refresh_dataset")
    def test_on_message_handles_nested_topic(self, mock_refresh, erddap_server, erddap_dataset):
        """on_message should extract dataset name from nested topics."""
        command = Command()
        command.stdout = StringIO()
        command.style = MagicMock()
        command.style.SUCCESS = lambda x: x

        on_message = command.create_on_message_callback(erddap_server)

        mock_msg = MagicMock()
        mock_msg.topic = "change/category/subcategory/test_dataset"

        on_message(None, None, mock_msg)

        mock_refresh.delay.assert_called_once_with(erddap_dataset.id)


@pytest.mark.django_db
class TestCreateMqttClient:
    """Tests for the create_mqtt_client method."""

    @pytest.fixture
    def erddap_server(self):
        """Create an ERDDAP server for testing."""
        return ErddapServer.objects.create(
            name="test-server",
            base_url="http://test.erddap.server/erddap",
            mqtt_broker="mqtt.test.server",
            mqtt_port=1883,
            mqtt_username="test_user",
            mqtt_password="test_password",
        )

    @patch("deployments.management.commands.erddap_mqtt.mqtt.Client")
    def test_creates_client_with_correct_api_version(self, mock_client_class, erddap_server):
        """create_mqtt_client should create client with CallbackAPIVersion.VERSION2."""
        import paho.mqtt.client as mqtt  # noqa: PLC0415

        command = Command()
        command.stdout = StringIO()
        command.style = MagicMock()

        command.create_mqtt_client(erddap_server)

        mock_client_class.assert_called_once()
        args, kwargs = mock_client_class.call_args
        assert args[0] == mqtt.CallbackAPIVersion.VERSION2

    @patch("deployments.management.commands.erddap_mqtt.mqtt.Client")
    def test_sets_username_and_password(self, mock_client_class, erddap_server):
        """create_mqtt_client should set username and password."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        command = Command()
        command.stdout = StringIO()
        command.style = MagicMock()

        command.create_mqtt_client(erddap_server)

        mock_client.username_pw_set.assert_called_once_with(
            username="test_user",
            password="test_password",
        )


@pytest.mark.django_db
class TestConnectAndRun:
    """Tests for the connect_and_run method."""

    @pytest.fixture
    def erddap_server(self):
        """Create an ERDDAP server for testing."""
        return ErddapServer.objects.create(
            name="test-server",
            base_url="http://test.erddap.server/erddap",
            mqtt_broker="mqtt.test.server",
            mqtt_port=1883,
            mqtt_username="test_user",
            mqtt_password="test_password",
        )

    def test_connects_with_correct_parameters(self, erddap_server):
        """connect_and_run should connect with correct broker, port, and timeout."""
        command = Command()
        command.stdout = StringIO()

        mock_client = MagicMock()
        # Mock loop_forever to stop immediately
        mock_client.loop_forever = MagicMock()

        command.connect_and_run(mock_client, erddap_server)

        mock_client.connect.assert_called_once_with("mqtt.test.server", 1883, 60)

    def test_calls_loop_forever(self, erddap_server):
        """connect_and_run should call loop_forever on the client."""
        command = Command()
        command.stdout = StringIO()

        mock_client = MagicMock()

        command.connect_and_run(mock_client, erddap_server)

        mock_client.loop_forever.assert_called_once()

    def test_raises_command_error_on_connection_failure(self, erddap_server):
        """connect_and_run should raise CommandError on connection failure."""
        command = Command()
        command.stdout = StringIO()

        mock_client = MagicMock()
        mock_client.connect.side_effect = Exception("Connection refused")

        with pytest.raises(CommandError, match="Unable to connect to MQTT broker"):
            command.connect_and_run(mock_client, erddap_server)


@pytest.mark.django_db
class TestHandleIntegration:
    """Integration tests for the handle method."""

    @pytest.fixture
    def erddap_server(self):
        """Create an ERDDAP server for testing."""
        return ErddapServer.objects.create(
            name="test-server",
            base_url="http://test.erddap.server/erddap",
            mqtt_broker="mqtt.test.server",
            mqtt_port=1883,
            mqtt_username="test_user",
            mqtt_password="test_password",
        )

    @patch("deployments.management.commands.erddap_mqtt.mqtt.Client")
    def test_handle_creates_and_runs_client(self, mock_client_class, erddap_server):
        """handle should create MQTT client and start the loop."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        out = StringIO()
        call_command("erddap_mqtt", "test-server", stdout=out)

        mock_client.connect.assert_called_once()
        mock_client.loop_forever.assert_called_once()

    @patch("deployments.management.commands.erddap_mqtt.mqtt.Client")
    def test_handle_writes_startup_message(self, mock_client_class, erddap_server):
        """handle should write a startup message."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        out = StringIO()
        call_command("erddap_mqtt", "test-server", stdout=out)

        assert "Starting ERDDAP MQTT subscriber" in out.getvalue()
