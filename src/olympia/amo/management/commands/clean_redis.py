import socket
import time

from django.conf import settings
from django.core.management.base import BaseCommand

import redis as redislib

import olympia.core.logger


log = olympia.core.logger.getLogger('z.redis')

# We process the keys in chunks of size CHUNK.
CHUNK = 3000
# Remove any sets with less than MIN or more than MAX elements.
MIN = 10
MAX = 50
# Expire keys after EXPIRE seconds.
EXPIRE = 60 * 5

# Calling redis can raise raise these errors.
RedisError = redislib.RedisError, socket.error


def cleanup(master, slave):
    total = [1, 0]

    def keys():
        try:
            ks = slave.keys()
        except RedisError:
            log.error('Cannot fetch keys.')
            raise
        total[0] = len(ks)
        log.info('There are %s keys to clean up.' % total[0])
        ks = iter(ks)
        while 1:
            buffer = []
            for _ in xrange(CHUNK):
                try:
                    buffer.append(next(ks))
                except StopIteration:
                    yield buffer
                    return
            yield buffer

    num = 0
    for ks in keys():
        pipe = slave.pipeline()
        for k in ks:
            pipe.scard(k)
        try:
            drop = [
                k
                for k, size in zip(ks, pipe.execute())
                if not k.startswith(settings.CACHE_PREFIX)
                or 0 < size < MIN
                or size > MAX
            ]
        except RedisError as err:
            log.warning('ignoring pipe.execute() error: {}'.format(err))
            continue
        num += len(ks)
        percent = round(float(num) / total[0] * 100, 1) if total[0] else 0
        total[1] += len(drop)
        log.debug('[%s %.1f%%] Dropping %s keys.' % (num, percent, len(drop)))
        pipe = master.pipeline()
        for k in drop:
            pipe.expire(k, EXPIRE)
        try:
            pipe.execute()
        except RedisError as err:
            log.warning('ignoring pipe.execute() error: {}'.format(err))
            continue
        time.sleep(1)  # Poor man's rate limiting.

    if total[0]:
        log.info(
            'Dropped %s keys [%.1f%%].'
            % (total[1], round(float(total[1]) / total[0] * 100, 1))
        )


def get_redis_backend(backend_uri):

    db = int(backend_uri.pop('DB', 0))
    host = backend_uri.pop('HOST', 'localhost')
    password = backend_uri.pop('PASSWORD', None)
    port = int(backend_uri.pop('PORT', 6379))

    try:
        socket_timeout = float(backend_uri['OPTIONS'].pop('socket_timeout'))
    except (KeyError, ValueError):
        socket_timeout = None

    return redislib.Redis(
        host=host,
        port=port,
        db=db,
        password=password,
        socket_timeout=socket_timeout,
    )


class Command(BaseCommand):
    help = "Clean up the redis used by cache machine."

    def handle(self, *args, **kw):
        try:
            master = get_redis_backend(settings.REDIS_BACKENDS['cache'])
            slave = get_redis_backend(settings.REDIS_BACKENDS['cache_slave'])
        except Exception:
            log.error('Could not connect to redis.')
            raise

        try:
            cleanup(master, slave)
        except Exception:
            log.error('Cleanup failed.')
            raise
