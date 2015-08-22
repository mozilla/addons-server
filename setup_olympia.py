"""Performs a number of path mutation and monkey patching operations which are
required for Olympia to start up correctly."""

import logging
import os
import site
import sys
import warnings


ROOT = os.path.dirname(os.path.abspath(__file__))

prev_sys_path = list(sys.path)

site.addsitedir(os.path.join(ROOT, 'apps'))

# Move the new items to the front of sys.path.
sys.path.sort(key=lambda name: name in prev_sys_path)

# Finally load the settings file that was specified.
from django.conf import settings  # noqa

if not settings.DEBUG:
    warnings.simplefilter('ignore')

import session_csrf  # noqa
session_csrf.monkeypatch()

# Fix jinja's Markup class to not crash when localizers give us bad format
# strings.
from jinja2 import Markup  # noqa
mod = Markup.__mod__
trans_log = logging.getLogger('z.trans')

# Waffle and amo form an import cycle because amo patches waffle and waffle
# loads the user model, so we have to make sure amo gets imported before
# anything else imports waffle.
import amo  # noqa

# Hardcore monkeypatching action.
import jingo.monkey  # noqa
jingo.monkey.patch()


def new(self, arg):
    try:
        return mod(self, arg)
    except Exception:
        trans_log.error(unicode(self))
        return ''

Markup.__mod__ = new

import djcelery  # noqa
djcelery.setup_loader()

# Import for side-effect: configures our logging handlers.
# pylint: disable-msg=W0611
from lib.log_settings_base import log_configure  # noqa
log_configure()

newrelic_ini = getattr(settings, 'NEWRELIC_INI', None)
load_newrelic = False

if newrelic_ini:
    import newrelic.agent
    try:
        newrelic.agent.initialize(newrelic_ini)
        load_newrelic = True
    except Exception:
        startup_logger = logging.getLogger('z.startup')
        startup_logger.exception('Failed to load new relic config.')
