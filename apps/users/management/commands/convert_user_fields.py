from django.core.management.base import BaseCommand
from django.db import connection

from celery.messaging import establish_connection


class Command(BaseCommand):

    help = """A one time command to convert user fields.  See
    http://blog.mozilla.com/addons/2010/07/26/upcoming-changes-to-amo-accounts/
    for details."""

    def handle(self, *args, **options):
        from users.tasks import add_usernames
        from amo.utils import chunked

        print "Getting users..."
        cursor = connection.cursor()
        # Doing this directly because I don't want to load 800k user objects
        cursor.execute("SELECT id, firstname, lastname, nickname FROM users")
        data = cursor.fetchall()

        with establish_connection() as conn:
            for chunk in chunked(data, 400):
               print "Sending data to celeryd..."
               add_usernames.apply_async(args=[chunk], connection=conn)
        print "All done."
