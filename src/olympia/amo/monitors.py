import os
import socket
import StringIO
import traceback

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import redis as redislib
import requests

from kombu import Connection
from PIL import Image

import olympia.core.logger

from olympia.amo import search
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.applications.management.commands import dump_apps


def memcache():
    memcache = getattr(settings, 'CACHES', {}).get('default')
    memcache_results = []
    status = ''
    if memcache and 'memcache' in memcache['BACKEND']:
        hosts = memcache['LOCATION']
        using_twemproxy = False
        if not isinstance(hosts, (tuple, list)):
            hosts = [hosts]
        for host in hosts:
            ip, port = host.split(':')

            if ip == '127.0.0.1':
                using_twemproxy = True

            try:
                s = socket.socket()
                s.connect((ip, int(port)))
            except Exception as e:
                result = False
                status = 'Failed to connect to memcached (%s): %s' % (host, e)
                monitor_log.critical(status)
            else:
                result = True
            finally:
                s.close()

            memcache_results.append((ip, port, result))
        if not using_twemproxy and len(memcache_results) < 2:
            status = ('2+ memcache servers are required.'
                      '%s available') % len(memcache_results)
            monitor_log.warning(status)

    if not memcache_results:
        status = 'Memcache is not configured'
        monitor_log.info(status)

    return status, memcache_results


def libraries():
    # Check Libraries and versions
    libraries_results = []
    status = ''
    try:
        Image.new('RGB', (16, 16)).save(StringIO.StringIO(), 'JPEG')
        libraries_results.append(('PIL+JPEG', True, 'Got it!'))
    except Exception as e:
        msg = "Failed to create a jpeg image: %s" % e
        libraries_results.append(('PIL+JPEG', False, msg))

    missing_libs = [l for l, s, m in libraries_results if not s]
    if missing_libs:
        status = 'missing libs: %s' % ",".join(missing_libs)
    return status, libraries_results


def elastic():
    elastic_results = None
    status = ''
    try:
        es = search.get_es()
        health = es.cluster.health()
        if health['status'] == 'red':
            status = 'ES is red'
        elastic_results = health
    except Exception:
        elastic_results = {'exception': traceback.format_exc()}

    return status, elastic_results


def path():
    # Check file paths / permissions
    rw = (settings.TMP_PATH,
          settings.MEDIA_ROOT,
          user_media_path('addons'),
          user_media_path('guarded_addons'),
          user_media_path('addon_icons'),
          user_media_path('collection_icons'),
          user_media_path('previews'),
          user_media_path('userpics'),
          user_media_path('reviewer_attachments'),
          dump_apps.Command.get_json_path(),)
    r = [os.path.join(settings.ROOT, 'locale'),
         # The deploy process will want write access to this.
         # We do not want Django to have write access though.
         settings.PROD_DETAILS_DIR]
    filepaths = [(path, os.R_OK | os.W_OK, 'We want read + write')
                 for path in rw]
    filepaths += [(path, os.R_OK, 'We want read') for path in r]
    filepath_results = []
    filepath_status = True

    for path, perms, notes in filepaths:
        path_exists = os.path.exists(path)
        path_perms = os.access(path, perms)
        filepath_status = filepath_status and path_exists and path_perms

        if not isinstance(path, str):
            notes += ' / should be a bytestring!'

        filepath_results.append((path, path_exists, path_perms, notes))

    status = filepath_status
    status = ''
    if not filepath_status:
        status = 'check main status page for broken perms / values'

    return status, filepath_results


def rabbitmq():
    # Check rabbitmq
    rabbitmq_results = []
    status = ''
    with Connection(settings.CELERY_BROKER_URL, connect_timeout=2) as broker:
        hostname = broker.hostname
        try:
            broker.connect()
            rabbitmq_results.append((hostname, True))
        except Exception as e:
            rabbitmq_results.append((hostname, False))
            status = 'Failed to chat with rabbitmq %s: %s' % (hostname, e)
            monitor_log.critical(status)

    return status, rabbitmq_results


def redis():
    # Check Redis
    redis_results = [None, 'REDIS_BACKENDS is not set']
    status = 'REDIS_BACKENDS is not set'
    if getattr(settings, 'REDIS_BACKENDS', False):
        status = []
        redis_results = {}

        for alias, backend in settings.REDIS_BACKENDS.items():
            if not isinstance(backend, dict):
                raise ImproperlyConfigured(
                    'REDIS_BACKENDS is now required to be a dictionary.')

            host = backend.get('HOST')
            port = backend.get('PORT')
            db = backend.get('DB', 0)
            password = backend.get('PASSWORD', None)
            socket_timeout = backend.get('OPTIONS', {}).get('socket_timeout')

            try:
                redis_connection = redislib.Redis(
                    host=host, port=port, db=db, password=password,
                    socket_timeout=socket_timeout)
                redis_results[alias] = redis_connection.info()
            except Exception as e:
                redis_results[alias] = None
                status.append('Failed to chat with redis:%s' % alias)
                monitor_log.critical('Failed to chat with redis: (%s)' % e)

        status = ','.join(status)

    return status, redis_results


def signer():
    # Check Signing Server Endpoint
    signer_results = None
    status = ''

    autograph_url = settings.AUTOGRAPH_CONFIG['server_url']
    if autograph_url:
        try:
            response = requests.get(
                '{host}/__heartbeat__'.format(host=autograph_url),
                timeout=settings.SIGNING_SERVER_MONITORING_TIMEOUT)
            if response.status_code != 200:
                status = (
                    'Failed to chat with signing service. '
                    'Invalid HTTP response code.')
                monitor_log.critical(status)
                signer_results = False
            else:
                signer_results = True
        except Exception as exc:
            status = 'Failed to chat with signing service: %s' % exc
            monitor_log.critical(status)
            signer_results = False
    else:
        status = 'server_url in AUTOGRAPH_CONFIG is not set'
        monitor_log.critical(status)
        signer_results = False

    return status, signer_results
