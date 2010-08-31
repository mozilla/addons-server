from optparse import make_option

from django.core.management.base import BaseCommand
from django.db import connection

from celery.messaging import establish_connection


class Command(BaseCommand):

    help = """A one time command to convert user fields.  See
    http://blog.mozilla.com/addons/2010/07/26/upcoming-changes-to-amo-accounts/
    for details."""

    option_list = BaseCommand.option_list + (
        make_option('--date', '-d', dest='date',
                    help='Only process accounts after this date.'),
        )

    def handle(self, *args, **options):
        from users.tasks import add_usernames
        from amo.utils import chunked

        date = options.get('date', False)

        print "Getting users..."
        cursor = connection.cursor()

        if date:
        # Doing this directly because I don't want to load 800k user objects
            query = """SELECT id, firstname, lastname, nickname
                       FROM users
                       WHERE modified > %s
                       OR created > %s"""
            cursor.execute(query, [date, date])
        else:
            cursor.execute("SELECT id, firstname, lastname, nickname FROM users")


        data = cursor.fetchall()

        with establish_connection() as conn:
            for chunk in chunked(data, 400):
               print "Sending data to celeryd..."
               add_usernames.apply_async(args=[chunk], connection=conn)
        print "All done."
