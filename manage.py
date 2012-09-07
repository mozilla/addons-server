#!/usr/bin/env python
import imp
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

# Figuring out what settings file to use.
# 1. Look first for the command line setting.
setting = None
if __name__ == '__main__':
    for k, v in enumerate(sys.argv):
        if v.startswith('--settings'):
            setting = v.split('=')[1]
            del sys.argv[k]
            break

# 2. If not, find the env variable.
if not setting:
    setting = os.environ.get('DJANGO_SETTINGS_MODULE', '')

# Django runserver does that double reload of installed settings, settings
# setting to zamboni.settings. We don't want to have zamboni on the path.
if setting.startswith(('zamboni',  # typical git clone destination
                       'workspace',  # Jenkins
                       'project',  # vagrant VM
                       'freddo')):
    setting = setting.split('.', 1)[1]

# The average Django user will have DJANGO_SETTINGS_MODULE set to settings
# for our purposes that means, load the default site, so if nothing is
# specified by now, use the default.
if setting in ('settings', ''):
    setting = 'settings_local'

# Finally load the settings file that was specified.
res = imp.find_module(setting)
settings = imp.load_module(setting, *res)
os.environ['DJANGO_SETTINGS_MODULE'] = setting

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

import djcelery
djcelery.setup_loader()

# Import for side-effect: configures our logging handlers.
# pylint: disable-msg=W0611
from lib.log_settings_base import log_configure
log_configure()

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
