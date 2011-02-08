import functools
import hashlib

from django.utils.encoding import smart_str
from django.core.cache import cache

import commonware.log
from redis.exceptions import ConnectionError

from translations.models import Translation

safe_key = lambda x: hashlib.md5(smart_str(x)).hexdigest()

log = commonware.log.getLogger('z.redis')


def add_redis(f):
    """
    Adds redis, if available, to a method call otherwise log's an error and
    returns None.
    """
    @functools.wraps(f)
    def wrapper(cls, *args, **kw):
        return_pipe = False
        if 'pipe' in kw and kw['pipe']:
            return_pipe = True

        try:
            import redisutils
            # TODO(davedash): This should be our persistence layer when that's
            # set in production.
            redis = redisutils.connections['master']
            pipe = redis.pipeline(transaction=True)
            ret = f(cls, redis, pipe, *args, **kw)
        except (AttributeError, ConnectionError):
            log.warning('Redis not available for %s' % f)
            return

        if return_pipe:
            return pipe
        else:
            pipe.execute()
            return ret
    return wrapper


class ReverseNameLookup(object):
    prefix = 'amo:addon:name'

    @classmethod
    @add_redis
    def add(cls, redis, pipe, name, addon_id):
        name = name.lower().strip()
        hash = safe_key(name)
        pipe.set('%s:%s' % (cls.prefix, hash), addon_id)
        pipe.sadd('%s:%d' % (cls.prefix, addon_id), hash)

    @classmethod
    @add_redis
    def get(cls, redis, pipe, key):
        key = key.lower().strip()
        val = redis.get('%s:%s' % (cls.prefix, safe_key(key)))
        if val:
            return int(val)

    @classmethod
    @add_redis
    def update(cls, redis, pipe, addon):
        cls.delete(addon.id, pipe=True)
        translations = (Translation.objects.filter(id=addon.name_id)
                        .values('localized_string', flat=True))
        for translation in translations:
            if translation:
                cls.add(translation.localized_string, addon.id, pipe=True)

    @classmethod
    @add_redis
    def delete(cls, redis, pipe, addon_id):
        hashes = redis.smembers('%s:%d' % (cls.prefix, addon_id))
        for hash in hashes:
            pipe.delete('%s:%s' % (cls.prefix, hash))
        pipe.delete('%s:%d' % (cls.prefix, addon_id))


#TODO(davedash): remove after remora
class ActivityLogMigrationTracker(object):
    """This tracks what id of the addonlog we're on."""
    key = 'amo:activitylog:migration'

    @add_redis
    def __init__(self, redis, pipe):
        self.redis = redis

    def get(self):
        return self.redis.get(self.key)

    def set(self, value):
        return self.redis.set(self.key, value)


#TODO(davedash): remove after admin is migrated
class AdminActivityLogMigrationTracker(ActivityLogMigrationTracker):
    """
    Per bug 628802:
    We will migrate activities from Remora admin.
    """
    key = 'amo:activitylog:admin_migration'


class MigrationTracker(object):
    @add_redis
    def __init__(self, redis, pipe, key):
        self.redis = redis
        self.key = 'amo:activitylog:%s' % key

    def get(self):
        return self.redis.get(self.key)

    def set(self, value):
        return self.redis.set(self.key, value)
