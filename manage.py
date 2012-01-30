#!/usr/bin/env python
import logging
import os
import site
import sys
import warnings


ROOT = os.path.dirname(os.path.abspath(__file__))
if os.path.splitext(os.path.basename(__file__))[0] == 'cProfile':
    if os.environ.get('ZAMBONI_PATH'):
        ROOT = os.environ['ZAMBONI_PATH']
    else:
        print 'When using cProfile you must set $ZAMBONI_PATH'
        sys.exit(2)

path = lambda *a: os.path.join(ROOT, *a)

prev_sys_path = list(sys.path)

site.addsitedir(path('apps'))
site.addsitedir(path('lib'))
site.addsitedir(path('vendor'))
site.addsitedir(path('vendor/lib/python'))

# Move the new items to the front of sys.path. (via virtualenv)
new_sys_path = []
for item in list(sys.path):
    if item not in prev_sys_path:
        new_sys_path.append(item)
        sys.path.remove(item)
sys.path[:0] = new_sys_path

# No third-party imports until we've added all our sitedirs!
from django.core.management import (call_command, execute_manager,
                                    setup_environ)

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

if not settings.DEBUG:
    warnings.simplefilter('ignore')

# The first thing execute_manager does is call `setup_environ`.  Logging config
# needs to access settings, so we'll setup the environ early.
setup_environ(settings)

# Hardcore monkeypatching action.
import safe_django_forms
safe_django_forms.monkeypatch()

import session_csrf
session_csrf.monkeypatch()

# Fix jinja's Markup class to not crash when localizers give us bad format
# strings.
from jinja2 import Markup
mod = Markup.__mod__
trans_log = logging.getLogger('z.trans')


def new(self, arg):
    try:
        return mod(self, arg)
    except Exception:
        trans_log.error(unicode(self))
        return ''

Markup.__mod__ = new

# Import for side-effect: configures our logging handlers.
# pylint: disable-msg=W0611
import log_settings

import djcelery
djcelery.setup_loader()

import safe_signals
safe_signals.start_the_machine()


if __name__ == "__main__":
    # If product details aren't present, get them.
    from product_details import product_details
    if not product_details.last_update:
        print 'Product details missing, downloading...'
        call_command('update_product_details')
        product_details.__init__()  # reload the product details

    execute_manager(settings)
