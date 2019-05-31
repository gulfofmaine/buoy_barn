from django.core.management.base import BaseCommand, CommandError
from django.db import connection, OperationalError


class Command(BaseCommand):
    help = "Check if the database is currently avaliable"

    def handle(self, *args, **kwargs):
        try:
            if connection.introspection.table_names():
                pass
        except OperationalError:
            raise CommandError("Database is not yet up")

        else:
            self.stdout.write("Database up")
