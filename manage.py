#!/usr/bin/env python
import sys


# This needs to be imported so it can perform path adjustments necessary for
# management command discovery, since that's one of the very few Django
# functions that doesn't import all apps.
from olympia import startup


if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
