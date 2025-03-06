import io
import os
import socket
import traceback
from urllib.parse import urljoin

from django.conf import settings

import celery
import MySQLdb
import requests
from django_statsd.clients import statsd
from kombu import Connection
from PIL import Image

import olympia.core.logger
from olympia.amo.models import use_primary_db
from olympia.blocklist.tasks import monitor_remote_settings
from olympia.search.utils import get_es


monitor_log = olympia.core.logger.getLogger('z.monitor')


def execute_checks(checks: list[str], verbose: bool = False):
    status_summary = {}
    for check in checks:
        with statsd.timer('monitor.%s' % check):
            status, results = globals()[check]()
        # state is a string. If it is empty, that means everything is fine.
        status_summary[check] = {'state': not status, 'status': status}
        if verbose:
            status_summary[check]['results'] = results
    return status_summary


def localdev_web():
    """
    Used in local development environments to determine if the web container
    is able to serve requests. The version endpoint returns a 200 status code
    and some json via the uwsgi http server.
    """
    status = ''
    try:
        response = requests.get('http://nginx/__version__')
        response.raise_for_status()
    except Exception as e:
        status = f'Failed to ping web: {e}'
        monitor_log.critical(status)

    return status, None


def celery_worker():
    """
    Used in local development environments to determine if the celery worker
    is able to execute tasks in the web worker.
    """
    status = ''
    app = celery.current_app

    inspector = app.control.inspect()

    if not inspector.ping():
        status = 'Celery worker is not connected'
        monitor_log.critical(status)

    return status, None


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
                status = f'Failed to connect to memcached ({host}): {e}'
                monitor_log.critical(status)
            else:
                result = True
            finally:
                s.close()

            memcache_results.append((ip, port, result))
        expected_count = settings.MEMCACHE_MIN_SERVER_COUNT
        if not using_twemproxy and len(memcache_results) < expected_count:
            status = ('%d+ memcache servers are required. %d available') % (
                expected_count,
                len(memcache_results),
            )
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
        Image.new('RGB', (16, 16)).save(io.BytesIO(), 'JPEG')
        libraries_results.append(('PIL+JPEG', True, 'Got it!'))
    except Exception as e:
        msg = 'Failed to create a jpeg image: %s' % e
        libraries_results.append(('PIL+JPEG', False, msg))

    missing_libs = [lib for lib, success, _ in libraries_results if not success]
    if missing_libs:
        status = 'missing libs: %s' % ','.join(missing_libs)
    return status, libraries_results


def elastic():
    elastic_results = None
    status = ''
    try:
        es = get_es()
        health = es.cluster.health()
        if health['status'] == 'red':
            status = 'ES is red'
        elastic_results = health
    except Exception:
        status = 'Failed to connect to Elasticsearch'
        elastic_results = {'exception': traceback.format_exc()}

    return status, elastic_results


def path():
    # Check file paths / permissions
    read_and_write = (
        settings.TMP_PATH,
        settings.MEDIA_ROOT,
        settings.ADDONS_PATH,
        os.path.join(settings.MEDIA_ROOT, 'addon_icons'),
        os.path.join(settings.MEDIA_ROOT, 'previews'),
        os.path.join(settings.MEDIA_ROOT, 'userpics'),
    )
    read_only = [os.path.join(settings.ROOT, 'locale')]
    filepaths = [
        (path, os.R_OK | os.W_OK, 'We want read + write') for path in read_and_write
    ]
    filepaths += [(path, os.R_OK, 'We want read') for path in read_only]
    filepath_results = []
    filepath_status = True

    for path, perms, notes in filepaths:
        path_exists = os.path.exists(path)
        path_perms = os.access(path, perms)
        filepath_status = filepath_status and path_exists and path_perms

        if not isinstance(path, bytes):
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
            status = f'Failed to chat with rabbitmq {hostname}: {e}'
            monitor_log.critical(status)

    return status, rabbitmq_results


def signer():
    # Check Signing Server Endpoint
    signer_results = None
    status = ''

    autograph_url = settings.AUTOGRAPH_CONFIG['server_url']
    if autograph_url:
        try:
            response = requests.get(
                f'{autograph_url}/__heartbeat__',
                timeout=settings.SIGNING_SERVER_MONITORING_TIMEOUT,
            )
            if response.status_code != 200:
                status = (
                    'Failed to chat with signing service. Invalid HTTP response code.'
                )
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


def olympia_database():
    """Check database connection by verifying the olympia database exists."""

    status = ''

    db_info = settings.DATABASES.get('default')

    engine = db_info.get('ENGINE').split('.')[-1]

    if engine != 'mysql':
        raise ValueError('expecting mysql database engine, recieved %s' % engine)

    mysql_args = {
        'user': db_info.get('USER'),
        'passwd': db_info.get('PASSWORD'),
        'host': db_info.get('HOST'),
    }
    if db_info.get('PORT'):
        mysql_args['port'] = int(db_info.get('PORT'))

    try:
        connection = MySQLdb.connect(**mysql_args)

        expected_db_name = db_info.get('NAME')
        connection.query(f'SHOW DATABASES LIKE "{expected_db_name}"')
        result = connection.store_result()

        if result.num_rows() == 0:
            status = f'Database {expected_db_name} does not exist'
            monitor_log.critical(status)
    except Exception as e:
        status = f'Failed to connect to database: {e}'
        monitor_log.critical(status)

    return status, None


def database():
    # check database connection
    from olympia.addons.models import Addon

    status = ''
    try:
        Addon.unfiltered.exists()
    except Exception as e:
        status = f'Failed to connect to replica database: {e}'
        monitor_log.critical(status)
    else:
        with use_primary_db():
            try:
                Addon.unfiltered.exists()
            except Exception as e:
                status = f'Failed to connect to primary database: {e}'
                monitor_log.critical(status)

    return status, None


def remotesettings():
    # TODO: We should be able to check remote settings
    # connectivity if the credentials are set.
    if settings.ENV in ('local', 'test'):
        return '', None
    # check Remote Settings connectivity.
    # Since the blocklist filter task is performed by
    # a worker, and since workers have different network
    # configuration than the Web head, we use a task to check
    # the connectivity to the Remote Settings server.
    # Since we want the result immediately, use original_apply_async() to avoid
    # waiting for the transaction django creates for the request like we
    # usually do.
    result = monitor_remote_settings.original_apply_async()
    try:
        status = result.get(timeout=settings.REMOTE_SETTINGS_CHECK_TIMEOUT_SECONDS)
    except celery.exceptions.TimeoutError as e:
        status = f'Failed to execute task in time: {e}'
        monitor_log.critical(status)
    return status, None


def cinder():
    # check cinder connectivity
    signer_results = None
    status = ''

    cinder_api_url = settings.CINDER_SERVER_URL
    if cinder_api_url:
        try:
            health_url = urljoin(cinder_api_url, '/health', allow_fragments=False)
            response = requests.get(health_url, timeout=5)
            response.raise_for_status()
        except Exception as exc:
            status = 'Failed to chat with cinder: %s' % exc
            monitor_log.critical(status)
            signer_results = False
        else:
            signer_results = True
    else:
        status = 'CINDER_SERVER_URL is not set'
        monitor_log.critical(status)
        signer_results = False

    return status, signer_results
