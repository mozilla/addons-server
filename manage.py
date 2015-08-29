#!/usr/bin/env python
import sys
# Required for sys.path setup prior to other imports.
import olympia  # noqa


if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
