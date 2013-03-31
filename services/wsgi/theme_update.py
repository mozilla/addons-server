import os
import site

wsgidir = os.path.dirname(__file__)
for path in ['../',
             '../..',
             '../../apps',
             '../../lib',
             '../../vendor/lib/python']:
    site.addsitedir(os.path.abspath(os.path.join(wsgidir, path)))

from ..theme_update import application
