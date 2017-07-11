import os
import logging
from datetime import datetime

log = logging.getLogger('z.startup')

# Remember when mod_wsgi loaded this file so we can track it in nagios.
wsgi_loaded = datetime.now()

# Tell celery that we're using Django.
os.environ['CELERY_LOADER'] = 'django'

import django
import django.conf
from django.core.wsgi import get_wsgi_application

# Do activate translations before running the app.
django.setup()
django.utils.translation.activate(django.conf.settings.LANGUAGE_CODE)

# This is what mod_wsgi runs.
django_app = get_wsgi_application()


# Normally we could let WSGIHandler run directly, but while we're dark
# launching, we want to force the script name to be empty so we don't create
# any /z links through reverse.  This fixes bug 554576.
def application(env, start_response):
    if 'HTTP_X_ZEUS_DL_PT' in env:
        env['SCRIPT_URL'] = env['SCRIPT_NAME'] = ''
    env['wsgi.loaded'] = wsgi_loaded
    env['hostname'] = django.conf.settings.HOSTNAME
    env['datetime'] = str(datetime.now())
    return django_app(env, start_response)


# Initialize Newrelic if we configured it
newrelic_ini = getattr(django.conf.settings, 'NEWRELIC_INI', None)

if newrelic_ini:
    import newrelic.agent
    try:
        newrelic.agent.initialize(newrelic_ini)
    except Exception:
        log.exception('Failed to load new relic config.')

    application = newrelic.agent.wsgi_application()(application)
