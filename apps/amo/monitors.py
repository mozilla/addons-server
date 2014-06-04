import os
import socket
import StringIO
import traceback

from django.conf import settings

import commonware.log
from PIL import Image

import amo.search
from amo.helpers import storage_path
from applications.management.commands import dump_apps

monitor_log = commonware.log.getLogger('z.monitor')


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
            except Exception, e:
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
    except Exception, e:
        msg = "Failed to create a jpeg image: %s" % e
        libraries_results.append(('PIL+JPEG', False, msg))

    try:
        import M2Crypto  # NOQA
        libraries_results.append(('M2Crypto', True, 'Got it!'))
    except ImportError:
        libraries_results.append(('M2Crypto', False, 'Failed to import'))

    if settings.SPIDERMONKEY:
        if os.access(settings.SPIDERMONKEY, os.R_OK):
            libraries_results.append(('Spidermonkey is ready!', True, None))
            # TODO: see if it works?
        else:
            msg = "You said spidermonkey was at (%s)" % settings.SPIDERMONKEY
            libraries_results.append(('Spidermonkey', False, msg))
    else:
        msg = "Please set SPIDERMONKEY in your settings file."
        libraries_results.append(('Spidermonkey', False, msg))

    missing_libs = [l for l, s, m in libraries_results if not s]
    if missing_libs:
        status = 'missing libs: %s' % ",".join(missing_libs)
    return status, libraries_results


def elastic():
    elastic_results = None
    status = ''
    try:
        health = amo.search.get_es().cluster_health()
        if health['status'] == 'red':
            status = 'ES is red'
        elastic_results = health
    except Exception:
        elastic_results = traceback.format_exc()

    return status, elastic_results


def path():
    # Check file paths / permissions
    rw = (settings.TMP_PATH,
          settings.MEDIA_ROOT,
          storage_path('addons'),
          storage_path('uploads'),
          storage_path('guarded_addons'),
          storage_path('mirror_stage'),
          storage_path('addon_icons'),
          storage_path('collection_icons'),
          settings.PACKAGER_PATH,
          storage_path('previews'),
          storage_path('userpics'),
          storage_path('reviewer_attachments'),
          settings.REVIEWER_ATTACHMENTS_PATH,
          dump_apps.Command.JSON_PATH,)
    r = [os.path.join(settings.ROOT, 'locale'),
         # The deploy process will want write access to this.
         # We do not want Django to have write access though.
         settings.PROD_DETAILS_DIR]
    filepaths = [(path, os.R_OK | os.W_OK, "We want read + write")
                 for path in rw]
    filepaths += [(path, os.R_OK, "We want read") for path in r]
    filepath_results = []
    filepath_status = True

    for path, perms, notes in filepaths:
        path_exists = os.path.exists(path)
        path_perms = os.access(path, perms)
        filepath_status = filepath_status and path_exists and path_perms
        filepath_results.append((path, path_exists, path_perms, notes))

    status = filepath_status
    status = ''
    if not filepath_status:
        status = 'check main status page for broken perms'

    return status, filepath_results


def redis():
    # Check Redis
    redis_results = [None, 'REDIS_BACKENDS is not set']
    status = 'REDIS_BACKENDS is not set'
    if getattr(settings, 'REDIS_BACKENDS', False):
        import redisutils
        status = []

        redis_results = {}

        for alias, redis in redisutils.connections.iteritems():
            try:
                redis_results[alias] = redis.info()
            except Exception, e:
                redis_results[alias] = None
                status.append('Failed to chat with redis:%s' % alias)
                monitor_log.critical('Failed to chat with redis: (%s)' % e)

        status = ','.join(status)

    return status, redis_results
