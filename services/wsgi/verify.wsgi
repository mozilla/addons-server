import os
import site

wsgidir = os.path.dirname(__file__)
for path in [
             '../',
             '../..',
             '../../vendor/src',
             '../../vendor/src/django',
             '../../vendor/src/nuggets',
             '../../vendor/src/commonware',
             '../../vendor/src/PyBrowserID',
             '../../vendor/src/statsd',
             '../../vendor/src/django-statsd',
             '../../vendor/src/tower',
             '../../vendor/src/pyjwt',
             '../../vendor/src/requests',
             '../../lib',
             '../../vendor/lib/python',
             '../../apps']:
    site.addsitedir(os.path.abspath(os.path.join(wsgidir, path)))

from verify import application
