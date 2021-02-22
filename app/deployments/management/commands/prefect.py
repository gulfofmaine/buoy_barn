import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from prefect.schedules import Schedule
from prefect.schedules.clocks import CronClock

from deployments.flows.reset_timeseries_end_times import (
    flow as reset_timeseries_end_times,
)


flows = {"reset_timeseries_end_times": reset_timeseries_end_times}

daily = Schedule(clocks=[CronClock("5 4 * * *")])


class Command(BaseCommand):
    help = "Run Prefect flow registration and/or agent"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--agent", help="Run local Prefect Agent", action="store_true"
        )
        parser.add_argument(
            "--register", help="Register flows with Prefect Cloud", action="store_true"
        )
        parser.add_argument("--run_flow", help="Run a specified flow by name")

    def handle(self, *args: Any, **options: Any):
        if options["run_flow"]:
            try:
                flow = flows[options["run_flow"]]
            except KeyError:
                raise CommandError(
                    f"Specified flow ({options['run_flow']}) does not exist"
                )

            flow.run()

        if options["register"]:
            self.register()
        else:
            self.stdout.write("Skipping registration of flows with Prefect Cloud")

        if options["agent"]:
            self.agent()
        else:
            self.stdout.write("Not running local Prefect Agent")

    def register(self):
        """ Handle flow registration """
        self.stdout.write("Registering flows with Prefect Cloud")

        try:
            project_name = os.environ["PREFECT_PROJECT_NAME"]
        except KeyError:
            raise CommandError(
                "`PREFECT_PROJECT_NAME` needs to be in the environment to register flows"
            )

        reset_timeseries_end_times.schedule = daily
        reset_timeseries_end_times.register(project_name=project_name)

    def agent(self):
        """ Run a local Prefect agent """
        self.stdout.write("Running local Prefect Agent")

        from prefect.agent.local.agent import LocalAgent

        agent = LocalAgent(show_flow_logs=True)

        agent.start()
