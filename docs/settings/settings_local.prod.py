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
CACHES = {
    'default': {
        'BACKEND': 'caching.backends.memcached.MemcachedCache',
        'LOCATION': ['localhost:11211', 'localhost:11212'],
        'TIMEOUT': 500,
    }
}

# This is used to hash some things in Django.
SECRET_KEY = 'replace me with something long'

LOG_LEVEL = logging.WARNING

DEBUG_PROPAGATE_EXCEPTIONS = DEBUG


# Sample metlog configuration. Uncommented, this would override what is in
# lib/settings_base.py.

# METLOG_CONF = {
#     'logger': 'zamboni',
#     'sender': {
#         'class': 'metlog.senders.UdpSender',
#         'host': ['10.0.1.5', '10.0.1.10']
#         'port': 5566
#     },
#     'plugins': {
#         'raven': ('metlog_raven.raven_plugin.config_plugin',
#                   {'sentry_project_id': 1}),
#     },
# }
#
# from metlog.config import client_from_dict_config
# METLOG = client_from_dict_config(METLOG_CONF)


# If you want to allow self-reviews for add-ons/apps, then enable this.
# In production we do not want to allow this.
ALLOW_SELF_REVIEWS = False
