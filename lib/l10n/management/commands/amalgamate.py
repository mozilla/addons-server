import os
import sys
from subprocess import Popen
from tempfile import TemporaryFile

from django.core.management.base import BaseCommand

from manage import settings

from translate.tools import pypo2phppo


class Command(BaseCommand):
    """
    This will merge zamboni strings into the current remora messages.po file
    in the PHP format.  This is not for the faint of heart.
    """

    def handle(self, *args, **options):

        locale_dir = os.path.join(settings.ROOT, 'locale')

        z_keys = os.path.join(locale_dir, 'z-keys.pot')
        r_keys = os.path.join(locale_dir, 'r-keys.pot')

        if not os.path.isfile(z_keys) or not os.path.isfile(r_keys):
            sys.exit("Can't find .pot files")

        # Step 1: Convert the zamboni .pot file to php format
        z_keys_file = open(z_keys)
        z_keys_python = TemporaryFile('w+t')

        if not pypo2phppo.convertpy2php(z_keys_file, z_keys_python):
            sys.exit(" Something is broken in (%s)" % z_keys_python)

        z_keys_file.close()

        merged = TemporaryFile('w+t')

        # Step 2: Merge the remora and zamboni .pot files together
        z_keys_python.seek(0)
        p1 = Popen(["msgcat", r_keys, "-"], stdin=z_keys_python,
                   stdout=merged)

        # Wait for process to terminate
        p1.communicate()

        for locale in os.listdir(locale_dir):
            if (not os.path.isdir(os.path.join(locale_dir, locale)) or
                    locale.startswith('.')):
                        continue

            r_messages = os.path.join(locale_dir, locale, 'LC_MESSAGES',
                                      'messages.po')

            if not os.path.isfile(r_messages):
                print " Can't find (%s).  Skipping..." % (r_messages)
                continue

            print "Mushing python strings into messages.po for %s" % (locale)

            # Step 3: Merge our new combined .pot with the .po file
            if locale == "en_US":
                merged.seek(0)
                enmerged = TemporaryFile('w+t')
                p3 = Popen(["msgen", "-"], stdin=merged, stdout=enmerged)
                p3.communicate()
                mergeme = enmerged
            else:
                mergeme = merged

            mergeme.seek(0)
            p2 = Popen(["msgmerge",
                        "--update",
                        "--no-fuzzy-matching",
                        "--sort-output",
                        "--width=200",
                        r_messages,
                        "-"],
                        stdin=mergeme)

            p2.communicate()

        print "finished"
