import functools
import hashlib
import logging

from django.utils.encoding import smart_str

import commonware.log
import redisutils
from redis.exceptions import ConnectionError

from translations.models import Translation

safe_key = lambda x: hashlib.md5(smart_str(x).lower().strip()).hexdigest()

log = commonware.log.getLogger('z.redis')
rnlog = logging.getLogger('z.rn')


class ReverseNameLookup(object):
    prefix = 'amo:addon:name'
    names = prefix + ':names'
    addons = prefix + ':addons'
    keys = prefix + ':keys'

    def __init__(self):
        self.redis = redisutils.connections['master']

    def add(self, name, addon_id):
        hash = safe_key(name)
        if not self.redis.hsetnx(self.names, hash, addon_id):
            rnlog.warning('Duplicate name: %s (%s).' % (name, addon_id))
            return
        rnlog.info('[%s] has a lock on "%s"' % (addon_id, name))
        self.redis.sadd('%s:%s' % (self.addons, addon_id), hash)
        self.redis.sadd(self.keys, addon_id)

    def get(self, key):
        val = self.redis.hget(self.names, safe_key(key))
        return int(val) if val else None

    def update(self, addon):
        self.delete(addon.id)
        translations = (Translation.objects.filter(id=addon.name_id)
                        .values('localized_string', flat=True))
        for translation in translations:
            if translation:
                self.add(unicode(translation.localized_string), addon.id)

    def delete(self, addon_id):
        rnlog.info('[%s] Releasing locked names.' % addon_id)
        hashes = self.redis.smembers('%s:%s' % (self.addons, addon_id))
        for hash in hashes:
            self.redis.hdel(self.names, hash)
        self.redis.delete('%s:%s' % (self.addons, addon_id))
        self.redis.srem(self.keys, addon_id)

    def clear(self):
        rnlog.info('Clearing the ReverseName table.')
        self.redis.delete(self.names)
        for key in self.redis.smembers(self.keys):
            self.redis.delete(key)


#TODO(davedash): remove after remora
class ActivityLogMigrationTracker(object):
    """This tracks what id of the addonlog we're on."""
    key = 'amo:activitylog:migration'

    def __init__(self):
        self.redis = redisutils.connections['master']

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

    def __init__(self, key):
        self.redis = redisutils.connections['master']
        self.key = 'amo:activitylog:%s' % key

    def get(self):
        return self.redis.get(self.key)

    def set(self, value):
        return self.redis.set(self.key, value)
