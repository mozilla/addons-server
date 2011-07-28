import hashlib
import logging
import random
from operator import itemgetter

from django.utils.encoding import smart_str

import commonware.log
import redisutils

from amo.utils import sorted_groupby
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


class FeaturedManager(object):
    prefix = 'addons:featured:'
    by_id = prefix + 'byid'
    by_app = classmethod(lambda cls, x: '%s:%s' % (cls.prefix + 'byapp', x))
    by_type = classmethod(lambda cls, x: '%s:%s' % (cls.prefix + 'bytype', x))
    by_locale = classmethod(lambda cls, x: '%s:%s' %
                            (cls.prefix + 'bylocale', x))

    @classmethod
    def redis(cls):
        return redisutils.connections['master']

    @classmethod
    def get_objects(cls):
        from addons.models import Feature
        return Feature.objects.values('addon', 'addon__type',
                                      'locale', 'application')

    @classmethod
    def build(cls):
        qs = list(cls.get_objects())
        by_type = sorted_groupby(qs, itemgetter('addon__type'))
        by_locale = sorted_groupby(qs, itemgetter('locale'))
        by_app = sorted_groupby(qs, itemgetter('application'))

        pipe = cls.redis().pipeline()
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
                    pipe.sadd(name, row['addon'])
        pipe.execute()

    @classmethod
    def featured_ids(cls, app, lang, type_=None):
        redis = cls.redis()
        base = (cls.by_id, cls.by_app(app.id))
        if type_ is not None:
            base += (cls.by_type(type_),)
        all_ = redis.sinter(base + (cls.by_locale(None),))
        per_locale = redis.sinter(base + (cls.by_locale(lang),))
        others = list(all_ - per_locale)
        per_locale = list(per_locale)
        random.shuffle(per_locale)
        random.shuffle(others)
        return map(int, per_locale + others)


class CreaturedManager(object):
    prefix = 'addons:creatured'
    by_cat = classmethod(lambda cls, cat: '%s:%s' % (cls.prefix, cat))
    by_locale = classmethod(lambda cls, cat, locale: '%s:%s:%s' %
                            (cls.prefix, cat, locale))

    @classmethod
    def redis(cls):
        return redisutils.connections['master']

    @classmethod
    def get_objects(cls):
        from addons.models import AddonCategory
        return (AddonCategory.objects.filter(feature=True)
                .values('category', 'addon', 'feature_locales'))

    @classmethod
    def build(cls):
        qs = list(cls.get_objects())
        # Expand any comma-separated lists of locales.
        for row in list(qs):
            # Normalize empty strings to None.
            if row['feature_locales'] == '':
                row['feature_locales'] = None
            if row['feature_locales']:
                qs.remove(row)
                for locale in row['feature_locales'].split(','):
                    d = dict(row)
                    d['feature_locales'] = locale.strip()
                    qs.append(d)

        pipe = cls.redis().pipeline()
        for category, rows in sorted_groupby(qs, itemgetter('category')):
            locale_getter = itemgetter('feature_locales')
            for locale, rs in sorted_groupby(rows, locale_getter):
                if locale:
                    name = cls.by_locale(category, locale)
                else:
                    name = cls.by_cat(category)
                pipe.delete(name)
                for row in rs:
                    pipe.sadd(name, row['addon'])
        pipe.execute()

    @classmethod
    def creatured_ids(cls, category, lang):
        redis = cls.redis()
        all_ = redis.smembers(cls.by_cat(category.id))
        per_locale = redis.smembers(cls.by_locale(category.id, lang))
        others = list(all_ - per_locale)
        per_locale = list(per_locale)
        random.shuffle(others)
        random.shuffle(per_locale)
        return map(int, per_locale + others)
