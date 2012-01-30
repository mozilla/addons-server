#!/usr/bin/env python
import getopt
import logging
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

prev_sys_path = list(sys.path)

# Boo, path manipulation we need to stop these.
site.addsitedir(path('apps'))
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
from django.utils import importlib

# Allow a user to pass in settings into manage.py and use that for our
# own purposes. If you don't use that we'll fall back to whatever is
# defined for DJANGO_SETTINGS_MODULE.
found, sys.argv[1:] = getopt.getopt(sys.argv[1:], 's:', 'settings=')
try:
    setting = dict(found).values()[0]
    if setting:
        os.environ['DJANGO_SETTINGS_MODULE'] = setting
except IndexError:
    pass

setting = os.environ.get('DJANGO_SETTINGS_MODULE', '')

# The average Django user will have DJANGO_SETTINGS_MODULE set to settings
# for our purposes that means, load the default site, so if nothing is
# specified by now, use the default.
if setting in ('settings', ''):
    setting = 'default'

# Because I'm lazy and want to type less characters, let's assume
# settings_local if not specified.
if not setting.endswith(('.settings_local', '.settings')):
    setting = setting + '.settings_local'

settings = importlib.import_module(setting)
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

logging = getattr(settings, 'ZAMBONI_LOGGING_FILE', None)
if logging:
    importlib.import_module(logging)

import djcelery
djcelery.setup_loader()

from lib.misc import safe_signals
safe_signals.start_the_machine()


if __name__ == "__main__":
    # If product details aren't present, get them.
    from product_details import product_details
    if not product_details.last_update:
        print 'Product details missing, downloading...'
        call_command('update_product_details')
        product_details.__init__()  # reload the product details

    execute_manager(settings)
