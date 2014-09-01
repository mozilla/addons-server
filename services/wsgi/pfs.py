import os
import site

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings_local")

wsgidir = os.path.dirname(__file__)
for path in ['../', '../..',
             '../../vendor/src',
             '../../vendor/src/django',
             '../../vendor/src/nuggets',
             '../../vendor/src/commonware',
             '../../vendor/src/statsd',
             '../../vendor/src/tower',
             '../../vendor/lib/python',
             '../../apps']:
    site.addsitedir(os.path.abspath(os.path.join(wsgidir, path)))

from ..pfs import application
