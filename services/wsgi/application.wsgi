import os
import site

wsgidir = os.path.dirname(__file__)
for path in ['../', '../..', '../../vendor/src/commonware',
             '../../vendor/src/django', '../../lib',
             '../../vendor/lib/python', '../../apps/versions']:
    site.addsitedir(os.path.abspath(os.path.join(wsgidir, path)))

from update import application
