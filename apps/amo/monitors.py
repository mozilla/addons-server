import os
import socket
import StringIO
import time
import traceback
from PIL import Image

from django.conf import settings

import commonware.log
import elasticutils.contrib.django as elasticutils

from amo.utils import memoize
from applications.management.commands import dump_apps
from lib.crypto import receipt

monitor_log = commonware.log.getLogger('z.monitor')


def memcache():
    memcache = getattr(settings, 'CACHES', {}).get('default')
    memcache_results = []
    status = True
    if memcache and 'memcached' in memcache['BACKEND']:
        hosts = memcache['LOCATION']
        if not isinstance(hosts, (tuple, list)):
            hosts = [hosts]
        for host in hosts:
            ip, port = host.split(':')
            try:
                s = socket.socket()
                s.connect((ip, int(port)))
            except Exception, e:
                result = False
                status = False
                monitor_log.critical('Failed to connect to memcached (%s): %s'
                                     % (host, e))
            else:
                result = True
            finally:
                s.close()

            memcache_results.append((ip, port, result))
        if len(memcache_results) < 2:
            status = False
            monitor_log.warning('You should have 2+ memcache servers. '
                                'You have %s.' % len(memcache_results))
    if not memcache_results:
        status = False
        monitor_log.info('Memcache is not configured.')

    return status, memcache_results


def libraries():
    # Check Libraries and versions
    libraries_results = []
    status = True
    try:
        Image.new('RGB', (16, 16)).save(StringIO.StringIO(), 'JPEG')
        libraries_results.append(('PIL+JPEG', True, 'Got it!'))
    except Exception, e:
        status = False
        msg = "Failed to create a jpeg image: %s" % e
        libraries_results.append(('PIL+JPEG', False, msg))

    try:
        import M2Crypto
        libraries_results.append(('M2Crypto', True, 'Got it!'))
    except ImportError:
        libraries_results.append(('M2Crypto', False, 'Failed to import'))

    if settings.SPIDERMONKEY:
        if os.access(settings.SPIDERMONKEY, os.R_OK):
            libraries_results.append(('Spidermonkey is ready!', True, None))
            # TODO: see if it works?
        else:
            status = False
            msg = "You said it was at (%s)" % settings.SPIDERMONKEY
            libraries_results.append(('Spidermonkey not found!', False, msg))
    else:
        status = False
        msg = "Please set SPIDERMONKEY in your settings file."
        libraries_results.append(("Spidermonkey isn't set up.", False, msg))

    return status, libraries_results


def elastic():
    elastic_results = None
    status = False
    try:
        health = elasticutils.get_es().cluster_health()
        status = health['status'] != 'red'
        elastic_results = health
    except Exception:
        elastic_results = traceback.format_exc()

    return status, elastic_results


def path():
    # Check file paths / permissions
    rw = (settings.TMP_PATH,
          settings.NETAPP_STORAGE,
          settings.UPLOADS_PATH,
          settings.ADDONS_PATH,
          settings.MIRROR_STAGE_PATH,
          settings.GUARDED_ADDONS_PATH,
          settings.ADDON_ICONS_PATH,
          settings.COLLECTIONS_ICON_PATH,
          settings.PACKAGER_PATH,
          settings.PREVIEWS_PATH,
          settings.IMAGEASSETS_PATH,
          settings.PERSONAS_PATH,
          settings.USERPICS_PATH,
          settings.WATERMARKED_ADDONS_PATH,
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

    key_exists = os.path.exists(settings.WEBAPPS_RECEIPT_KEY)
    key_perms = os.access(settings.WEBAPPS_RECEIPT_KEY, os.R_OK)
    filepath_status = filepath_status and key_exists and key_perms
    filepath_results.append(('settings.WEBAPPS_RECEIPT_KEY',
                             key_exists, key_perms, 'We want read'))

    status = filepath_status

    return status, filepath_results


def redis():
    # Check Redis
    redis_results = [None, 'REDIS_BACKENDS is not set']
    if getattr(settings, 'REDIS_BACKENDS', False):
        import redisutils

        redis_results = {}

        for alias, redis in redisutils.connections.iteritems():
            try:
                redis_results[alias] = redis.info()
            except Exception, e:
                redis_results[alias] = None
                monitor_log.critical('Failed to chat with redis: (%s)' % e)

    status = all(i for i in redis_results.values())

    return status, redis_results


# The signer check actually asks the signing server to sign something. Do this
# once per nagios check, once per web head might be a bit much. The memoize
# slows it down a bit, by caching the result once per minute.
@memoize('monitors-signer', time=60 * 5)
def signer():
    destination = getattr(settings, 'SIGNING_SERVER', None)
    if not destination:
        return True, 'Signer is not configured.'

    # Just send some test data into the signer.
    now = int(time.time())
    not_valid = (settings.SITE_URL + '/not-valid')
    data = {'detail': not_valid, 'exp': now + 3600, 'iat': now,
            'iss': settings.SITE_URL,
            'product': {'storedata': 'id=1', 'url': u'http://not-valid.com'},
            'nbf': now, 'typ': 'purchase-receipt',
            'reissue': not_valid,
            'user': {'type': 'directed-identifier',
                     'value': u'something-not-valid'},
            'verify': not_valid
    }

    try:
        result = receipt.sign(data)
    except receipt.SigningError, err:
        return False, 'Error on signing (%s): %s' % (destination, err)

    try:
        cert, rest = receipt.crack(result)
    except Exception, err:
        return False, 'Error on cracking receipt (%s): %s' % (destination, err)

    # Check that the certs used to sign the receipts are not about to expire.
    limit = now + (60 * 60 * 24)  # One day.
    if cert['exp'] < limit:
        return False, 'Cert will expire soon (%s)' % destination
    return True, 'Signer working and up to date'
