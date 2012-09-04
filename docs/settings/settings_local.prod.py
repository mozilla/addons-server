from settings import *

DEBUG = False
TEMPLATE_DEBUG = False

# The default database should point to the master.
DATABASES = {
    'default': {
        'NAME': 'zamboni',
        'ENGINE': 'django.db.backends.mysql',
        'HOST': '',
        'PORT': '',
        'USER': '',
        'PASSWORD': '',
        'OPTIONS': {'init_command': 'SET storage_engine=InnoDB'},
    },
    'slave': {
        'NAME': 'zamboni',
        'ENGINE': 'django.db.backends.mysql',
        'HOST': '',
        'PORT': '',
        'USER': '',
        'PASSWORD': '',
        'OPTIONS': {'init_command': 'SET storage_engine=InnoDB'},
    },
}

# Put the aliases for slave databases in this list.
SLAVE_DATABASES = ['slave']

# Use IP:PORT pairs separated by semicolons.
CACHE_BACKEND = 'django_pylibmc.memcached://localhost:11211;localhost:11212?timeout=500'

# This is used to hash some things in Django.
SECRET_KEY = 'replace me with something long'

# Remove any apps that are only needed for development.
INSTALLED_APPS = tuple(app for app in INSTALLED_APPS if app not in DEV_APPS)

LOG_LEVEL = logging.WARNING

DEBUG_PROPAGATE_EXCEPTIONS = DEBUG


# Sample metlog configuration. Uncommented, this would override what is in
# lib/settings_base.py.

# METLOG_CONF = {
#     'logger': 'zamboni',
#     'sender': {
#         'class': 'metlog.senders.UdpSender',
#         'host': '127.0.0.1',
#         'port': '5566',
#     },
#     'plugins': {
#         'raven': ('metlog_raven.raven_plugin.config_plugin',
#                   {'sentry_project_id': 1}),
#     },
# }
#
# from metlog.config import client_from_dict_config
# METLOG = client_from_dict_config(METLOG_CONF)
