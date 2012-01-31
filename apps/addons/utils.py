import hashlib
import logging
import random
from operator import itemgetter

from django.conf import settings
from django.utils.encoding import smart_str

import commonware.log
from lib.misc import lru_cache
import redisutils

from amo.utils import sorted_groupby, memoize
from translations.models import Translation

safe_key = lambda x: hashlib.md5(smart_str(x).lower().strip()).hexdigest()

log = commonware.log.getLogger('z.redis')
rnlog = logging.getLogger('z.rn')


class ReverseNameLookup(object):

    def __init__(self, webapp=False):
        self.redis = redisutils.connections['master']
        self.type = 'app' if webapp else 'addon'
        self.prefix = 'amo:%s:name' % self.type
        self.names = self.prefix + ':names'
        self.addons = self.prefix + ':addons'
        self.keys = self.prefix + ':keys'

    def add(self, name, addon_id):
        hash = safe_key(name)
        if not self.redis.hsetnx(self.names, hash, addon_id):
            rnlog.warning('Duplicate %s name: %s (%s).' % (
                self.type, name, addon_id))
            return
        rnlog.info('[%s:%s] has a lock on "%s"' % (self.type, addon_id, name))
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
        rnlog.info('[%s:%s] Releasing locked names.' % (self.type, addon_id))
        hashes = self.redis.smembers('%s:%s' % (self.addons, addon_id))
        for hash in hashes:
            self.redis.hdel(self.names, hash)
        self.redis.delete('%s:%s' % (self.addons, addon_id))
        self.redis.srem(self.keys, addon_id)

    def clear(self):
        rnlog.info('Clearing the %s ReverseName table.' % self.type)
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


class FeaturedManager(object):
    prefix = 'addons:featured:'
    by_id = prefix + 'byid'
    by_app = classmethod(lambda cls, x: '%s:%s' % (cls.prefix + 'byapp', x))
    by_type = classmethod(lambda cls, x: '%s:%s' % (cls.prefix + 'bytype', x))
    by_locale = classmethod(lambda cls, x: '%s:%s' %
                            (cls.prefix + 'bylocale', x and x.lower()))

    @classmethod
    def redis(cls):
        return redisutils.connections['master']

    @classmethod
    def _get_objects(cls):
        fields = ['addon', 'type', 'locale', 'application']
        from bandwagon.models import FeaturedCollection
        vals = (FeaturedCollection.objects
                .filter(collection__addons__isnull=False)
                .values_list('collection__addons',
                             'collection__addons__type', 'locale',
                             'application'))
        return [dict(zip(fields, val)) for val in vals]

    @classmethod
    def get_objects(cls):
        rv = cls._get_objects()
        for d in rv:
            if d['locale']:
                d['locale'] = d['locale'].lower()
        return rv

    @classmethod
    def build(cls):
        qs = list(cls.get_objects())
        # Normalize empty values.
        for row in qs:
            if not row['locale']:
                row['locale'] = None

        by_type = sorted_groupby(qs, itemgetter('type'))
        by_locale = sorted_groupby(qs, itemgetter('locale'))
        by_app = sorted_groupby(qs, itemgetter('application'))

        pipe = cls.redis().pipeline(transaction=False)
        pipe.delete(cls.by_id)
        for row in qs:
            pipe.sadd(cls.by_id, row['addon'])

        groups = zip((cls.by_type, cls.by_locale, cls.by_app),
                     (by_type, by_locale, by_app))
        for prefixer, group in groups:
            for key, rows in group:
                name = prefixer(key)
                pipe.delete(name)
                for row in rows:
                    if row['addon']:
                        pipe.sadd(name, row['addon'])
        pipe.execute()

    @classmethod
    @lru_cache.lru_cache(maxsize=100)
    @memoize(prefix, time=60 * 10)
    def featured_ids(cls, app, lang=None, type=None):
        redis = cls.redis()
        base = (cls.by_id, cls.by_app(app.id))
        if type is not None:
            base += (cls.by_type(type),)
        if lang:
            all_ = redis.sinter(base + (cls.by_locale(None),))
            per_locale = redis.sinter(base + (cls.by_locale(lang),))
        else:
            all_ = redis.sinter(base)
            per_locale = set()
        others = list(all_ - per_locale)
        per_locale = list(per_locale)
        random.shuffle(per_locale)
        random.shuffle(others)
        return map(int, filter(None, per_locale + others))


class CreaturedManager(object):
    prefix = 'addons:creatured'

    @classmethod
    def by_cat(cls, cat, app):
        return '%s:%s:%s' % (cls.prefix, cat, app)

    @classmethod
    def by_locale(cls, cat, app, locale):
        return '%s:%s:%s:%s' % (cls.prefix, cat, app, locale.lower())

    @classmethod
    def redis(cls):
        return redisutils.connections['master']

    @classmethod
    def _get_objects(cls):
        fields = ['category', 'addon', 'locales', 'app']
        from bandwagon.models import FeaturedCollection
        vals = (FeaturedCollection.objects
                .filter(collection__addons__isnull=False)
                .values_list('collection__addons__category',
                             'collection__addons', 'locale',
                             'application'))
        return [dict(zip(fields, val)) for val in vals]

    @classmethod
    def get_objects(cls):
        rv = cls._get_objects()
        for d in rv:
            if d['locales']:
                d['locales'] = d['locales'].lower()
        return rv

    @classmethod
    def build(cls):
        qs = list(cls.get_objects())
        # Expand any comma-separated lists of locales.
        for row in list(qs):
            # Normalize empty strings to None.
            if row['locales'] == '':
                row['locales'] = None
            if row['locales']:
                qs.remove(row)
                for locale in row['locales'].split(','):
                    d = dict(row)
                    d['locales'] = locale.strip()
                    qs.append(d)

        pipe = cls.redis().pipeline(transaction=False)
        catapp = itemgetter('category', 'app')
        for (category, app), rows in sorted_groupby(qs, catapp):
            locale_getter = itemgetter('locales')
            for locale, rs in sorted_groupby(rows, locale_getter):
                if locale:
                    name = cls.by_locale(category, app, locale)
                else:
                    name = cls.by_cat(category, app)
                pipe.delete(name)
                for row in rs:
                    if row['addon']:
                        pipe.sadd(name, row['addon'])
        pipe.execute()

    @classmethod
    @lru_cache.lru_cache(maxsize=100)
    @memoize(prefix, time=60 * 10)
    def creatured_ids(cls, category, lang):
        redis = cls.redis()
        all_ = redis.smembers(cls.by_cat(category.id, category.application_id))
        locale_key = cls.by_locale(category.id, category.application_id, lang)
        per_locale = redis.smembers(locale_key)
        others = list(all_ - per_locale)
        per_locale = list(per_locale)
        random.shuffle(others)
        random.shuffle(per_locale)
        return map(int, filter(None, per_locale + others))
