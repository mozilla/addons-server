import os
import sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from celery.messaging import establish_connection


class Command(BaseCommand):

    args = "<file>"

    help = """This command accepts a new-line separated file of user id's to
    delete from the database.  See [1] for the policy.

    [1]
    http://blog.mozilla.com/addons/2010/07/26/upcoming-changes-to-amo-accounts/
    """

    def handle(self, *args, **options):
        # Avoiding loops
        from amo.utils import chunked, slugify
        from users.models import UserProfile
        from users.tasks import _delete_users

        if not args:
            print "Usage: manage.py delete_users <file>"
            sys.exit(1)


        if not os.path.exists(args[0]):
            print "File not found: %s" % args[0]
            sys.exit(1)

        f = open(args[0], 'r')

        data = True

        print "Reading %s" % args[0]

        while data:
            data = f.readlines(100000)  # 100000 is about 13500 user ids
            data = [x.strip() for x in data]  # has newlines on it

            print "Sending %s users to celery" % len(data)

            with establish_connection() as conn:
                for chunk in chunked(data, 100):
                    _delete_users.apply_async(args=[chunk], connection=conn)

        f.close()

        print "All done."
