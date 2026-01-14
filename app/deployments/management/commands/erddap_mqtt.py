import uuid

import paho.mqtt.client as mqtt
from django.core.management.base import BaseCommand, CommandError, CommandParser

from deployments.models import ErddapDataset, ErddapServer
from deployments.tasks import single_refresh_dataset

client_id = f"buoy-barn-mqtt-subscriber-{uuid.getnode()}"


class Command(BaseCommand):
    help = "Start the ERDDAP MQTT subscriber"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "server_slug",
            help="The slug/name of the ERDDAP server to subscribe to",
            type=str,
        )

    def handle(self, *args, **options):
        server_slug = options["server_slug"]

        erddap_server = ErddapServer.objects.get(name=server_slug)

        if not erddap_server.mqtt_broker:
            raise CommandError(f"No MQTT broker configured for ERDDAP server {erddap_server}")

        if not erddap_server.mqtt_username or not erddap_server.mqtt_password:
            raise CommandError(f"No MQTT credentials configured for ERDDAP server {erddap_server}")

        self.stdout.write(f"Starting ERDDAP MQTT subscriber for {erddap_server}")

        def on_connect(client, userdata, flags, reason_code, properties):
            self.stdout.write(
                f"Connected to MQTT broker ({erddap_server.mqtt_broker}) for {erddap_server}",
            )
            client.subscribe("change/#")
            self.stdout.write(self.style.SUCCESS(f"Subscribed to change/# topics for {erddap_server}"))

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

        mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        mqttc.on_connect = on_connect
        mqttc.on_message = on_message

        mqttc.username_pw_set(username=erddap_server.mqtt_username, password=erddap_server.mqtt_password)

        try:
            mqttc.connect(erddap_server.mqtt_broker, erddap_server.mqtt_port, 60)
        except Exception as e:
            raise CommandError(f"Unable to connect to MQTT broker: {e}") from None

        mqttc.loop_forever()
