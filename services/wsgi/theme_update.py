import os
import site

os.environ['DJANGO_SETTINGS_MODULE'] = 'settings_local'

wsgidir = os.path.dirname(__file__)
for path in ['../',
             '../..',
             '../../apps',
             '../../vendor/lib/python']:
    site.addsitedir(os.path.abspath(os.path.join(wsgidir, path)))

from ..theme_update import application
