from django.core.cache import cache

from nose.tools import eq_

from test_utils import ExtraAppTestCase
import caching.base as caching

from testapp.models import Addon, User


class CachingTestCase(ExtraAppTestCase):
    fixtures = ['testapp/test_cache.json']
    extra_apps = ['caching.tests.testapp']

    def setUp(self):
        cache.clear()

    def test_flush_key(self):
        """flush_key should work for objects or strings."""
        a = Addon.objects.get(id=1)
        eq_(caching.flush_key(a), 'flush:%s' % a.cache_key)
        eq_(caching.flush_key(a.cache_key), caching.flush_key(a))

    def test_cache_key(self):
        a = Addon.objects.get(id=1)
        eq_(a.cache_key, 'o:testapp.addon:1')

        keys = set((a.cache_key, a.author1.cache_key, a.author2.cache_key))
        eq_(set(a._cache_keys()), keys)

    def test_cache(self):
        """Basic cache test: second get comes from cache."""
        assert Addon.objects.get(id=1).from_cache is False
        assert Addon.objects.get(id=1).from_cache is True

    def test_invalidation(self):
        assert Addon.objects.get(id=1).from_cache is False
        a = [x for x in Addon.objects.all() if x.id == 1][0]
        assert a.from_cache is False

        assert Addon.objects.get(id=1).from_cache is True
        a = [x for x in Addon.objects.all() if x.id == 1][0]
        assert a.from_cache is True

        a.save()
        assert Addon.objects.get(id=1).from_cache is False
        a = [x for x in Addon.objects.all() if x.id == 1][0]
        assert a.from_cache is False

    def test_fk_invalidation(self):
        """When an object is invalidated, its foreign keys get invalidated."""
        a = Addon.objects.get(id=1)
        assert User.objects.get(name='clouseroo').from_cache is False
        a.save()

        assert User.objects.get(name='clouseroo').from_cache is False

    def test_fk_parent_invalidation(self):
        """When a foreign key changes, any parent objects get invalidated."""
        assert Addon.objects.get(id=1).from_cache is False
        a = Addon.objects.get(id=1)
        assert a.from_cache is True

        u = User.objects.get(id=a.author1.id)
        assert u.from_cache is True
        u.name = 'fffuuu'
        u.save()

        assert User.objects.get(id=a.author1.id).from_cache is False
        a = Addon.objects.get(id=1)
        assert a.from_cache is False
        eq_(a.author1.name, 'fffuuu')

    def test_raw_cache(self):
        sql = 'SELECT * FROM %s WHERE id = 1' % Addon._meta.db_table
        raw = list(Addon.objects.raw(sql))
        eq_(len(raw), 1)
        raw_addon = raw[0]
        a = Addon.objects.get(id=1)
        for field in Addon._meta.fields:
            eq_(getattr(a, field.name), getattr(raw_addon, field.name))
        assert raw_addon.from_cache is False

        cached = list(Addon.objects.raw(sql))
        eq_(len(cached), 1)
        cached_addon = cached[0]
        a = Addon.objects.get(id=1)
        for field in Addon._meta.fields:
            eq_(getattr(a, field.name), getattr(cached_addon, field.name))
        assert cached_addon.from_cache is True

    def test_raw_cache_params(self):
        """Make sure the query params are included in the cache key."""
        sql = 'SELECT * from %s WHERE id = %%s' % Addon._meta.db_table
        raw = list(Addon.objects.raw(sql, [1]))[0]
        eq_(raw.id, 1)

        raw2 = list(Addon.objects.raw(sql, [2]))[0]
        eq_(raw2.id, 2)
