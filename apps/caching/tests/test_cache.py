from nose.tools import eq_

from test_utils import ExtraAppTestCase
import caching

from testapp.models import Addon, User


class CachingTestCase(ExtraAppTestCase):
    fixtures = ['testapp/test_cache.json']
    extra_apps = ['caching.tests.testapp']

    def setUp(self):
        caching.cache.clear()

    def test_flush_key(self):
        """flush_key should work for objects or strings."""
        a = Addon.objects.get(id=1)
        eq_(caching.flush_key(a), 'flush:%s' % a.cache_key)
        eq_(caching.flush_key(a.cache_key), caching.flush_key(a))

    def test_cache_key(self):
        a = Addon.objects.get(id=1)
        eq_(a.cache_key, 'o:testapp.addon:1')

        eq_(a._cache_keys(), (a.cache_key, a.author1.cache_key,
                              a.author2.cache_key))

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
