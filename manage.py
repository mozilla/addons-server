#!/usr/bin/env python
import os
import site
import sys


ROOT = os.path.dirname(os.path.abspath(__file__))
if os.path.splitext(os.path.basename(__file__))[0] == 'cProfile':
    if os.environ.get('ZAMBONI_PATH'):
        ROOT = os.environ['ZAMBONI_PATH']
    else:
        print 'When using cProfile you must set $ZAMBONI_PATH'
        sys.exit(2)

path = lambda *a: os.path.join(ROOT, *a)

site.addsitedir(path('apps'))
site.addsitedir(path('lib'))
site.addsitedir(path('vendor'))

# No third-party imports until we've added all our sitedirs!
from django.core.management import execute_manager, setup_environ

try:
    import settings_local as settings
except ImportError:
    try:
        import settings
    except ImportError:
        import sys
        sys.stderr.write(
            "Error: Tried importing 'settings_local.py' and 'settings.py' "
            "but neither could be found (or they're throwing an ImportError)."
            " Please come back and try again later.")
        raise

# The first thing execute_manager does is call `setup_environ`.  Logging config
# needs to access settings, so we'll setup the environ early.
setup_environ(settings)

# Import for side-effect: configures our logging handlers.
# pylint: disable-msg=W0611
import log_settings


if __name__ == "__main__":
    execute_manager(settings)
