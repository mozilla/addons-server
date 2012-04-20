import os
import sys
from django.core.files.storage import default_storage as storage
from django.core.management.base import BaseCommand


class Command(BaseCommand):

    help = """Convert non-png files to png files.  One time script,
              for bug 731102, based heavily on the one in bug 593267."""

    def handle(self, *args, **options):
        from django.conf import settings
        from amo.utils import resize_image

        converted = 0
        for path in (settings.COLLECTIONS_ICON_PATH, settings.PREVIEWS_PATH):
            if not os.path.isdir(path):
                sys.exit("Can't read pics path: %s" % path)

            for root, dirs, files in storage.walk(path):
                for file in files:
                    # Aside from 9 files missing extentsions entirely (!)
                    # everything is jpg or gif or png
                    if file[-4:] in ('.jpg', '.gif'):
                        name, _ = os.path.splitext(file)
                        oldfile = "%s/%s" % (root, file)
                        newfile = "%s/%s.png" % (root, name)

                        if storage.exists(newfile):
                            print "Removing pre-existing file: %s" % (newfile)
                        storage.delete(newfile)

                        print "Converting %s to %s" % (oldfile, newfile)
                        try:
                            resize_image(oldfile, newfile)
                        except IOError, e:
                            print "ERROR: (%s => %s) %s" % (oldfile, newfile, e)
                        converted += 1
                        if converted % 100 == 0:
                            print "Converted %s images..." % converted

                    elif file.endswith('.png'):
                        pass
                    else:
                        print "Not sure what to do with: %s" % file

        # Thumbnails are already all .pngs so no need to adjust them
        print """All done.  Now you should run this SQL:

                    UPDATE collections
                        SET modified=NOW(),
                            icontype = "image/png" WHERE icontype !='';

                    UPDATE previews
                        SET modified=NOW(),
                            filetype = "image/png" WHERE filetype !='';

              """
