import logging
import socket
import time

from django.conf import settings
from django.core.cache import parse_backend_uri
from django.core.management.base import BaseCommand

import redis as redislib

log = logging.getLogger('z.redis')

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
                    buffer.append(ks.next())
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
            drop = [k for k, size in zip(ks, pipe.execute())
                    if 0 < size < MIN or size > MAX]
        except RedisError, err:
            log.warn('ignoring pipe.execute() error: {}'.format(err))
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
        except RedisError, err:
            log.warn('ignoring pipe.execute() error: {}'.format(err))
            continue
        time.sleep(1)  # Poor man's rate limiting.

    if total[0]:
        log.info('Dropped %s keys [%.1f%%].' % (
            total[1], round(float(total[1]) / total[0] * 100, 1)))


def get_redis_backend(backend_uri):
    # From django-redis-cache
    # This is temporary https://github.com/washort/nuggets/pull/1
    _, server, params = parse_backend_uri(backend_uri)
    db = params.pop('db', 1)
    try:
        db = int(db)
    except (ValueError, TypeError):
        db = 0
    try:
        socket_timeout = float(params.pop('socket_timeout'))
    except (KeyError, ValueError):
        socket_timeout = None
    password = params.pop('password', None)
    if ':' in server:
        host, port = server.split(':')
        try:
            port = int(port)
        except (ValueError, TypeError):
            port = 6379
    else:
        host = 'localhost'
        port = 6379
    return redislib.Redis(host=host, port=port, db=db, password=password,
                          socket_timeout=socket_timeout)


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
