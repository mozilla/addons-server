import os
import site

wsgidir = os.path.dirname(__file__)
for path in ['../', '../..',
             '../../vendor/src',
             '../../vendor/src/django',
             '../../vendor/src/nuggets',
             '../../vendor/src/commonware',
             '../../vendor/src/tower',
             '../../lib',
             '../../vendor/lib/python',
             '../../apps']:
    site.addsitedir(os.path.abspath(os.path.join(wsgidir, path)))

from update import application
