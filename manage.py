#!/usr/bin/env python
import logging
import os
import site
import sys
import warnings


ROOT = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    path = lambda *a: os.path.join(ROOT, *a)

    prev_sys_path = list(sys.path)

    site.addsitedir(path('apps'))
    site.addsitedir(path('vendor/lib/python'))

    # Move the new items to the front of sys.path. (via virtualenv)
    new_sys_path = []
    for item in list(sys.path):
        if item not in prev_sys_path:
            new_sys_path.append(item)
            sys.path.remove(item)
    sys.path[:0] = new_sys_path

    # No third-party imports until we've added all our sitedirs!
    from django.core.management import call_command, execute_from_command_line

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

    # Finally load the settings file that was specified.
    from django.conf import settings

    if not settings.DEBUG:
        warnings.simplefilter('ignore')

    import session_csrf
    session_csrf.monkeypatch()

    # Fix jinja's Markup class to not crash when localizers give us bad format
    # strings.
    from jinja2 import Markup
    mod = Markup.__mod__
    trans_log = logging.getLogger('z.trans')

    # Waffle and amo form an import cycle because amo patches waffle and waffle
    # loads the user model, so we have to make sure amo gets imported before
    # anything else imports waffle.
    import amo  # noqa

    # Hardcore monkeypatching action.
    import jingo.monkey
    jingo.monkey.patch()

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

    newrelic_ini = getattr(settings, 'NEWRELIC_INI', None)
    load_newrelic = False

    if newrelic_ini:
        import newrelic.agent
        try:
            newrelic.agent.initialize(newrelic_ini)
            load_newrelic = True
        except:
            startup_logger = logging.getLogger('z.startup')
            startup_logger.exception('Failed to load new relic config.')

    # If product details aren't present, get them.
    from product_details import product_details
    if not product_details.last_update:
        print 'Product details missing, downloading...'
        call_command('update_product_details')
        product_details.__init__()  # reload the product details

    execute_from_command_line(sys.argv)
