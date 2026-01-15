import uuid

import paho.mqtt.client as mqtt
from django.core.management.base import BaseCommand, CommandError, CommandParser

from deployments.models import ErddapDataset, ErddapServer
from deployments.tasks import single_refresh_dataset


def get_client_id() -> str:
    """Generate a unique client ID for the MQTT connection."""
    return f"buoy-barn-mqtt-subscriber-{uuid.getnode()}"


class Command(BaseCommand):
    help = "Start the ERDDAP MQTT subscriber"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "server_slug",
            help="The slug/name of the ERDDAP server to subscribe to",
            type=str,
        )

    def get_erddap_server(self, server_slug: str) -> ErddapServer:
        """Retrieve and validate the ERDDAP server configuration."""
        try:
            erddap_server = ErddapServer.objects.get(name=server_slug)
        except ErddapServer.DoesNotExist:
            raise CommandError(f"ERDDAP server with slug '{server_slug}' not found") from None

        if not erddap_server.mqtt_broker:
            raise CommandError(f"No MQTT broker configured for ERDDAP server {erddap_server}")

        if not erddap_server.mqtt_username or not erddap_server.mqtt_password:
            raise CommandError(f"No MQTT credentials configured for ERDDAP server {erddap_server}")

        return erddap_server

    def create_on_connect_callback(self, erddap_server: ErddapServer):
        """Create the on_connect callback for the MQTT client."""

        def on_connect(client, userdata, flags, reason_code, properties):
            self.stdout.write(
                f"Connected to MQTT broker ({erddap_server.mqtt_broker}) for {erddap_server}",
            )
            client.subscribe("change/#")
            self.stdout.write(self.style.SUCCESS(f"Subscribed to change/# topics for {erddap_server}"))

        return on_connect

    def create_on_message_callback(self, erddap_server: ErddapServer):
        """Create the on_message callback for the MQTT client."""

        def on_message(client, userdata, msg):
            dataset_name = msg.topic.split("/")[-1]
            self.stdout.write(f"ERDDAP dataset updated: {dataset_name}")
            try:
                dataset = ErddapDataset.objects.get(name=dataset_name, server=erddap_server)
            except ErddapDataset.DoesNotExist:
                self.stdout.write(
                    self.style.NOTICE(
                        f"No dataset found for name {dataset_name} on server {erddap_server}",
                    ),
                )
                return
            single_refresh_dataset.delay(dataset.id)
            self.stdout.write(self.style.SUCCESS(f"Scheduled refresh for dataset {dataset}"))

        return on_message

    def create_mqtt_client(self, erddap_server: ErddapServer) -> mqtt.Client:
        """Create and configure the MQTT client."""
        mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=get_client_id())
        mqttc.on_connect = self.create_on_connect_callback(erddap_server)
        mqttc.on_message = self.create_on_message_callback(erddap_server)
        mqttc.username_pw_set(username=erddap_server.mqtt_username, password=erddap_server.mqtt_password)
        return mqttc

    def connect_and_run(self, mqttc: mqtt.Client, erddap_server: ErddapServer) -> None:
        """Connect to the MQTT broker and start the message loop."""
        try:
            mqttc.connect(erddap_server.mqtt_broker, erddap_server.mqtt_port, 60)
        except Exception as e:
            raise CommandError(f"Unable to connect to MQTT broker: {e}") from None

        mqttc.loop_forever()

    def handle(self, *args, **options):
        server_slug = options["server_slug"]

        erddap_server = self.get_erddap_server(server_slug)

        self.stdout.write(f"Starting ERDDAP MQTT subscriber for {erddap_server}")

        mqttc = self.create_mqtt_client(erddap_server)
        self.connect_and_run(mqttc, erddap_server)
