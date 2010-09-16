import os
import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):

    help = """Detect png files on disk that aren't in the database and add the
              link to them in the db.  See bug 596477."""

    def handle(self, *args, **options):
        from amo.utils import chunked
        from celery.messaging import establish_connection
        from django.conf import settings
        from users.tasks import fix_users_with_photos

        if not os.path.isdir(settings.USERPICS_PATH):
            sys.exit("Can't read pics path: %s" % settings.USERPICS_PATH)

        pile_of_users = []

        print "Looking for images in %s..." % settings.USERPICS_PATH
        for root, dirs, files in os.walk(settings.USERPICS_PATH):
            for file in files:
                root, ext = os.path.splitext(file)
                if ext == '.png':
                    # We build up a big list of users who have pictures
                    pile_of_users.append(root)

        print "I found %s images.  Sending IDs to celeryd..." % len(pile_of_users)

        with establish_connection() as conn:
            for chunk in chunked(pile_of_users, 200):
                fix_users_with_photos.apply_async(args=[chunk], connection=conn)

        print "All done."
