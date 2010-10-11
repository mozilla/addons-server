import os
import sys

SETTINGS_DIR = os.path.realpath(
        os.path.join(os.path.dirname(__file__), os.path.sep.join(('..',) * 2)))

sys.path.append(SETTINGS_DIR)
sys.path.append(os.path.join(SETTINGS_DIR, 'lib'))

from manage import settings

s = settings.DATABASES['default']
MYSQL_PASS = s['PASSWORD']
MYSQL_USER = s['USER']
MYSQL_HOST = s.get('HOST', 'localhost')
MYSQL_NAME = s['NAME']
TEST_NAME = s.get('TEST_NAME', 'test_' + MYSQL_NAME)

CATALOG_PATH = settings.SPHINX_CATALOG_PATH
LOG_PATH = settings.SPHINX_LOG_PATH
ETC_PATH = os.path.dirname(settings.SPHINX_CONFIG_PATH)
LISTEN_PORT = settings.SPHINX_PORT
MYSQL_LISTEN_PORT = settings.SPHINXQL_PORT
MYSQL_LISTEN_HOST = 'localhost'

if MYSQL_HOST.endswith('.sock'):
    MYSQL_HOST = 'localhost'

if os.environ.get('DJANGO_ENVIRONMENT') == 'test':
    MYSQL_NAME = TEST_NAME
    CATALOG_PATH = settings.TEST_SPHINX_CATALOG_PATH
    LOG_PATH = settings.TEST_SPHINX_LOG_PATH
    LISTEN_PORT = settings.TEST_SPHINX_PORT
    MYSQL_LISTEN_PORT = settings.TEST_SPHINXQL_PORT
