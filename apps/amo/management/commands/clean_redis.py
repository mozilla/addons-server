import logging
import os
import socket
import subprocess
import sys
import tempfile
import time

from django.core.management.base import BaseCommand

import redisutils
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


def vacuum(master, slave):

    def keys():
        ks = slave.keys()
        log.info('There are %s keys to clean up.' % len(ks))
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

    tmp = tempfile.NamedTemporaryFile(delete=False)
    for ks in keys():
        tmp.write('\n'.join(ks))
    tmp.close()

    # It's hard to get Python to clean up the memory from slave.keys(), so
    # we'll let the OS do it. You have to pass sys.executable both as the
    # thing to run and so argv[0] is set properly.
    os.execl(sys.executable, sys.executable, sys.argv[0],
             sys.argv[1], tmp.name)


def cleanup(master, slave, filename):
    tmp = open(filename)
    total = [1, 0]
    p = subprocess.Popen(['wc', '-l', filename], stdout=subprocess.PIPE)
    total[0] = int(p.communicate()[0].strip().split()[0])

    def file_keys():
        while 1:
            buffer = []
            for _ in xrange(CHUNK):
                line = tmp.readline()
                if line:
                    buffer.append(line.strip())
                else:
                    yield buffer
                    return
            yield buffer

    num = 0
    for ks in file_keys():
        pipe = slave.pipeline()
        for k in ks:
            pipe.scard(k)
        try:
            drop = [k for k, size in zip(ks, pipe.execute())
                    if 0 < size < MIN or size > MAX]
        except RedisError:
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
        except RedisError:
            continue
        time.sleep(1)  # Poor man's rate limiting.

    if total[0]:
        log.info('Dropped %s keys [%.1f%%].' % (
            total[1], round(float(total[1]) / total[0] * 100, 1)))


class Command(BaseCommand):
    help = "Clean up the redis used by cache machine."

    def handle(self, *args, **kw):
        try:
            master = redisutils.connections['cache']
            slave = redisutils.connections['cache_slave']
        except Exception:
            log.error('Could not connect to redis.', exc_info=True)
            return
        if args:
            filename = args[0]
            try:
                cleanup(master, slave, filename)
            finally:
                os.unlink(filename)
        else:
            vacuum(master, slave)
