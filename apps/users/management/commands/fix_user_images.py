import os
import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):

    help = """Convert non-png files to png files.  One time script,
              see bug 593267."""

    def handle(self, *args, **options):
        from django.conf import settings
        from users.tasks import delete_photo, resize_photo

        if not os.path.isdir(settings.USERPICS_PATH):
            sys.exit("Can't read pics path: %s" % settings.USERPICS_PATH)

        converted = 0
        for root, dirs, files in os.walk(settings.USERPICS_PATH):
            for file in files:
                if file[-4:] in ('.jpg', '.gif'):
                    name, _ = os.path.splitext(file)
                    oldfile = "%s/%s" % (root, file)
                    newfile = "%s/%s.png" % (root, name)

                    if os.path.isfile(newfile):
                        delete_photo(oldfile)
                    else:
                        resize_photo(oldfile, newfile)
                        converted += 1
                        if converted % 100 == 0:
                            print "Converted %s images..." % converted

                elif file.endswith('.png') or file.endswith('__unconverted'):
                    pass
                else:
                    print "Not sure what to do with: %s" % file
        print "All done."
