"""
WSGI endpoint for addons-server.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/howto/deployment/wsgi/
"""

from django.core.wsgi import get_wsgi_application


# This is referenced in docker/uwsgi.ini: module = olympia.wsgi:application
application = get_wsgi_application()
