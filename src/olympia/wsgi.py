import django
import django.conf
import django.core.management
import django.utils

from django.core.wsgi import get_wsgi_application


# Do validate and activate translations before running the app.
django.setup()
django.utils.translation.activate(django.conf.settings.LANGUAGE_CODE)


# This is referenced in docker/uwsgi.ini: module = olympia.wsgi:application
def application(env, start_response):
    return get_wsgi_application()(env, start_response)
