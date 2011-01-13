import itertools
import logging
import socket
import tempfile
import time

from django.core.management.base import BaseCommand

import redisutils
import redis as redislib

log = logging.getLogger('z.redis')

# We process the keys in chunks of size CHUNK.
CHUNK = 3000
# Remove any sets with less than MIN or more than MAX elements.
MIN = 2
MAX = 75
# Expire keys after EXPIRE seconds.
EXPIRE = 60 * 5

# Calling redis can raise raise these errors.
RedisError = redislib.RedisError, socket.error


def vacuum(master, slave):
    total = [1, 0]

    def keys():
        ks = slave.keys()
        total[0] = len(ks)
        log.info('There are %s keys to clean up.' % total[0])
        ks = iter(ks)
        while 1:
            yield [ks.next() for _ in xrange(CHUNK)]

    tmp = tempfile.TemporaryFile()
    for ks in keys():
        tmp.write('\n'.join(ks))
    tmp.seek(0)

    def file_keys():
        while 1:
            # Get about 300 keys.
            x = tmp.readlines(1024 * 30)
            if x:
                yield [k.strip() for k in x]
            else:
                raise StopIteration

    count = itertools.count()
    for ks in file_keys():
        pipe = slave.pipeline()
        for k in ks:
            pipe.scard(k)
        try:
            drop = [k for k, size in zip(ks, pipe.execute())
                    if size < MIN or size > MAX]
        except RedisError:
            continue
        num = count.next() * CHUNK
        percent = round(float(num) / total[0] * 100, 1)
        total[1] += len(drop)
        log.debug('[%s %.1f%%] Dropping %s keys.' % (num, percent, len(drop)))
        pipe = master.pipeline()
        for k in drop:
            pipe.expire(k, EXPIRE)
        try:
            pipe.execute()
        except RedisError:
            continue
        time.sleep(1)  # Poor man's rate limiting.

    if total[0]:
        log.info('Dropped %s keys [%.1f%%].' %
                  (total[1], round(float(total[1]) / total[0] * 100, 1)))


class Command(BaseCommand):
    help = "Clean up the redis used by cache machine."

    def handle(self, *args, **kw):
        try:
            master = redisutils.connections['cache']
            slave = redisutils.connections['cache_slave']
        except Exception:
            log.error('Could not connect to redis.', exc_info=True)
            return
        vacuum(master, slave)
