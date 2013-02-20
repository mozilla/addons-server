import os
import socket
import StringIO
import time
import traceback
from PIL import Image

from django.conf import settings

import commonware.log
import elasticutils.contrib.django as elasticutils
import requests

from amo.utils import memoize
from applications.management.commands import dump_apps
from lib.crypto import receipt
from lib.crypto.receipt import SigningError

monitor_log = commonware.log.getLogger('z.monitor')


def memcache():
    memcache = getattr(settings, 'CACHES', {}).get('default')
    memcache_results = []
    status = ''
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
                status = 'Failed to connect to memcached (%s): %s' % (host, e)
                monitor_log.critical(status)
            else:
                result = True
            finally:
                s.close()

            memcache_results.append((ip, port, result))
        if len(memcache_results) < 2:
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
        import M2Crypto
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
        health = elasticutils.get_es().cluster_health()
        if health['status'] == 'red':
            status = 'ES is red'
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


# The signer check actually asks the signing server to sign something. Do this
# once per nagios check, once per web head might be a bit much. The memoize
# slows it down a bit, by caching the result for 15 seconds.
@memoize('monitors-signer', time=15)
def signer():
    destination = getattr(settings, 'SIGNING_SERVER', None)
    if not destination:
        return '', 'Signer is not configured.'

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
    except SigningError as err:
        msg = 'Error on signing (%s): %s' % (destination, err)
        return msg, msg

    try:
        cert, rest = receipt.crack(result)
    except Exception as err:
        msg = 'Error on cracking receipt (%s): %s' % (destination, err)
        return msg, msg

    # Check that the certs used to sign the receipts are not about to expire.
    limit = now + (60 * 60 * 24)  # One day.
    if cert['exp'] < limit:
        msg = 'Cert will expire soon (%s)' % destination
        return msg, msg

    cert_err_msg = 'Error on checking public cert (%s): %s'
    location = cert['iss']
    try:
        resp = requests.get(location, timeout=5, prefetch=True)
    except Exception as err:
        msg = cert_err_msg % (location, err)
        return msg, msg

    if not resp.ok:
        msg = cert_err_msg % (location, resp.reason)
        return msg, msg

    cert_json = resp.json
    if not cert_json or not 'jwk' in cert_json:
        msg = cert_err_msg % (location, 'Not valid JSON/JWK')
        return msg, msg

    return '', 'Signer working and up to date'
