import os
import re

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.management.base import BaseCommand


_loc_re = re.compile(r"""\\?(loc)\(.*?\)""", (re.M | re.S))
_exts = ('.py', '.html')
_root = settings.ROOT
_subs = tuple([os.path.join(_root, s) for s in ['apps']])


class Command(BaseCommand):
    """
    A very simple parser to find string marked with loc in py and html.
    This is rather naive, so don't worry about it being perfect, it's just
    so that we can find all the strings for the marketplace and pass them on
    to UX people. Or you could do a fancy grep.
    """
    def handle(self, *args, **options):
        count = 0
        for root, folders, files in storage.walk(_root):
            if not root.startswith(_subs):
                continue

            for fname in files:
                fname = os.path.join(root, fname)
                if fname.endswith(_exts):
                    data = storage.open(fname).read()
                    found = False
                    for match in _loc_re.finditer(data):
                        if not found:
                            found = True
                            print fname
                            print '-' * len(fname)
                        print match.string[match.start():match.end()]
                        count += 1

                    if found:
                        print

        print 'Strings found:', count
