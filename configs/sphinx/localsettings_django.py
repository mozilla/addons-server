import os
import sys

SETTINGS_DIR = os.path.realpath(
        os.path.join(os.path.dirname(__file__), os.path.sep.join(('..',)*2)))

sys.path.append(SETTINGS_DIR)
sys.path.append(os.path.join(SETTINGS_DIR,'lib'))

import settings_local as settings

s = settings.DATABASES['default']
MYSQL_PASS = s['PASSWORD']
MYSQL_USER = s['USER']
MYSQL_HOST = s.get('HOST', 'localhost')
MYSQL_NAME = s['NAME']

if MYSQL_HOST.endswith('.sock'):
    MYSQL_HOST = 'localhost'

if os.environ.get('DJANGO_ENVIRONMENT') == 'test':
    MYSQL_NAME = 'test_' + MYSQL_NAME


BASE_PATH = '/tmp'
CATALOG_PATH      = BASE_PATH + '/data/sphinx'
LOG_PATH          = BASE_PATH + '/log/searchd'
ETC_PATH          = BASE_PATH + '/etc'
LISTEN_PORT       = 3312
MYSQL_LISTEN_PORT = 3307
MYSQL_LISTEN_HOST = 'localhost'
