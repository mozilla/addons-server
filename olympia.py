"""Performs a number of path mutation and monkey patching operations which are
required for Olympia to start up correctly.

This is imported into manage.py and wsgi.py.

This is executed when celery starts up by way of `bin/celery --app=olympia`
where `olympia` is this module.

This docstring will probably be wrong by the time you read it.
"""

import logging
import os
import sys
import warnings


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")


def update_system_path():
    """Add our `apps` directory to the front of `sys.path` so our app modules
    are importable without the `apps.` prefix."""

    ROOT = os.path.dirname(os.path.abspath(__file__))
    # Insert the 'apps' folder to the front of sys.path so it takes precedence.
    sys.path.insert(0, os.path.join(ROOT, 'apps'))


def filter_warnings():
    """Ignore Python warnings unless we're running in debug mode."""
    # Do not import this from the top-level. It depends on set-up from the
    # functions above.
    from django.conf import settings

    if not settings.DEBUG:
        warnings.simplefilter('ignore')


def init_session_csrf():
    """Load the `session_csrf` module and enable its monkey patches to
    Django's CSRF middleware."""
    import session_csrf
    session_csrf.monkeypatch()


def init_jinja2():
    """Monkeypatch jinja2's Markup class to handle errors from bad `%` format
    operations, due to broken strings from localizers."""
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


def init_jingo():
    """Load Jingo and trigger its Django monkey patches, so it supports the
    `__html__` protocol used by Jinja2 and MarkupSafe."""
    import jingo.monkey
    jingo.monkey.patch()


def init_amo():
    """Load the `amo` module.

    Waffle and amo form an import cycle because amo patches waffle and waffle
    loads the user model, so we have to make sure amo gets imported before
    anything else imports waffle."""
    global amo
    amo = __import__('amo')


def init_celery():
    """
    Initialize Celery, and make our app instance available as `celery_app`
    for use by the `celery` command.
    """
    from django.conf import settings
    from raven import Client
    from raven.contrib.celery import register_signal, register_logger_signal
    from amo import celery

    # I think `manage.py celery` relies on this global? We typically don't run
    # celery like that anymore though.
    global celery_app
    celery_app = celery.app

    # Hook up Sentry in celery.
    client = Client(settings.SENTRY_DSN)

    # register a custom filter to filter out duplicate logs
    register_logger_signal(client)

    # hook into the Celery error handler
    register_signal(client)

    # After upgrading raven we can specify loglevel=logging.INFO to override
    # the default (which is ERROR).
    register_logger_signal(client)


def configure_logging():
    """Configure the `logging` module to route logging based on settings
    in our various settings modules and defaults in `lib.log_settings_base`."""
    from lib.log_settings_base import log_configure

    log_configure()


def init_newrelic():
    """Init NewRelic, if we're configured to use it."""
    # Do not import this from the top-level. It depends on set-up from the
    # functions above.
    from django.conf import settings

    newrelic_ini = getattr(settings, 'NEWRELIC_INI', None)
    if newrelic_ini:
        import newrelic.agent
        try:
            newrelic.agent.initialize(newrelic_ini)
            global load_newrelic
            load_newrelic = True
        except Exception:
            log.exception('Failed to load new relic config.')


def load_product_details():
    """Fetch product details, if we don't already have them."""
    from product_details import product_details

    if not product_details.last_update:
        from django.core.management import call_command

        log.info('Product details missing, downloading...')
        call_command('update_product_details')
        product_details.__init__()  # reload the product details


log = logging.getLogger('z.startup')
load_newrelic = False

update_system_path()
filter_warnings()
init_session_csrf()
init_jinja2()
init_amo()
configure_logging()
init_jingo()
init_celery()
init_newrelic()
load_product_details()
