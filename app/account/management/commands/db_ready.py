import time

from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, connection


def check_db_connection() -> bool:
    """Returns True if the database is up"""
    try:
        connection.introspection.table_names()
        return True
    except OperationalError:
        return False


class Command(BaseCommand):
    help = "Check if the database is currently available"  # noqa: A003

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            help="Retry for given number of seconds",
            type=int,
        )

    def handle(self, *args, **options):
        timeout = options["timeout"] if options["timeout"] else 0
        self.stdout.write(f"Checking for a maximum of {timeout} seconds")

        for _ in range(timeout + 1):
            if check_db_connection():
                self.stdout.write("Database is up")
                break
            time.sleep(1)
        else:
            raise CommandError("Database is not yet up")
