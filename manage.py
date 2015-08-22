#!/usr/bin/env python
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import setup_olympia  # noqa

# No third-party imports until we've added all our sitedirs!
from django.core.management import (call_command,
                                    execute_from_command_line)  # noqa


if __name__ == "__main__":

    # If product details aren't present, get them.
    from product_details import product_details
    if not product_details.last_update:
        print 'Product details missing, downloading...'
        call_command('update_product_details')
        product_details.__init__()  # reload the product details

    execute_from_command_line(sys.argv)
