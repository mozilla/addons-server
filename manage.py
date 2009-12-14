#!/usr/bin/env python
import site

from django.core.management import execute_manager, setup_environ


try:
    import local_settings as settings
except ImportError:
    try:
        import settings
    except ImportError:
        import sys
        sys.stderr.write(
            "Error: Tried importing 'local_settings.py' and 'settings.py' "
            "but neither could be found (or they're throwing an ImportError)."
            " Please come back and try again later.")


site.addsitedir(settings.path('apps'))
site.addsitedir(settings.path('lib'))

# The first thing execute_manager does is call `setup_environ`.  Logging config
# needs to access settings, so we'll setup the environ early.
setup_environ(settings)

# Import for side-effect: configures our logging handlers.
import log_settings


if __name__ == "__main__":
    execute_manager(settings)
