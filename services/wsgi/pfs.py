import os
import site

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings_local")

wsgidir = os.path.dirname(__file__)
for path in ['../', '../..',
             '../../apps']:
    site.addsitedir(os.path.abspath(os.path.join(wsgidir, path)))

from ..pfs import application  # noqa
