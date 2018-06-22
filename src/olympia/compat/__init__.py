import olympia.core.logger
from olympia import amo
from olympia.search.utils import floor_version


# This is a list of dictionaries that we should generate compat info for.
# main: the app version we're generating compat info for.
# versions: version numbers to show in comparisons.
# previous: the major version before :main.

if amo.FIREFOX.latest_version:
    # We only generate compatibility info for the last 8 major versions.
    latest_version = int(float(floor_version(amo.FIREFOX.latest_version)))
    FIREFOX_COMPAT = [{
        'main': floor_version(v),
        'versions': (floor_version(v),
                     floor_version(v) + 'a2',
                     floor_version(v) + 'a1'),
        'previous': floor_version(v - 1)
    } for v in range(latest_version, latest_version - 9, -1)]
else:
    # Why don't you have `product_details` like the rest of us?
    log.warning('You are missing `product_details`. '
                'Run `python manage.py update_product_details` now.')

    FIREFOX_COMPAT = {}
