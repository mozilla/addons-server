#!/usr/bin/env python
from django.core.management import execute_manager

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


if __name__ == "__main__":
    execute_manager(settings)
