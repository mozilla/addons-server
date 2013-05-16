import os
import site
import sys
from datetime import datetime

# Tell manage that we need to pull in the default settings file.
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings_local_mkt'

# Remember when mod_wsgi loaded this file so we can track it in nagios.
wsgi_loaded = datetime.now()

# Tell celery that we're using Django.
os.environ['CELERY_LOADER'] = 'django'

# Add the zamboni dir to the python path so we can import manage.
wsgidir = os.path.dirname(__file__)
site.addsitedir(os.path.abspath(os.path.join(wsgidir, '../')))

# manage adds /apps, /lib, and /vendor to the Python path.
import manage

import django.conf
import django.core.handlers.wsgi
import django.core.management
import django.utils

# Do validate and activate translations like using `./manage.py runserver`.
# http://blog.dscpl.com.au/2010/03/improved-wsgi-script-for-use-with.html
django.utils.translation.activate(django.conf.settings.LANGUAGE_CODE)
utility = django.core.management.ManagementUtility()
command = utility.fetch_command('runserver')
command.validate()

# This is what mod_wsgi runs.
django_app = django.core.handlers.wsgi.WSGIHandler()

newrelic_ini = getattr(django.conf.settings, 'NEWRELIC_INI', None)
load_newrelic = False

if newrelic_ini:
    import newrelic.agent
    try:
        newrelic.agent.initialize(newrelic_ini)
        load_newrelic = True
    except:
        import logging
        startup_logger = logging.getLogger('z.startup')
        startup_logger.exception('Failed to load new relic config.')


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


if load_newrelic:
    application = newrelic.agent.wsgi_application()(application)
# Uncomment this to figure out what's going on with the mod_wsgi environment.
# def application(env, start_response):
#     start_response('200 OK', [('Content-Type', 'text/plain')])
#     return '\n'.join('%r: %r' % item for item in sorted(env.items()))

# vim: ft=python
