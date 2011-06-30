import itertools
import random

import mock
import test_utils
from nose.tools import eq_

import amo
from addons.models import Addon, AddonCategory, AddonRecommendation, Category
from bandwagon.models import (Collection, CollectionAddon, CollectionUser,
                              CollectionWatcher, SyncedCollection,
                              RecommendedCollection, FeaturedCollection)
from devhub.models import ActivityLog
from bandwagon import tasks
from users.models import UserProfile


def get_addons(c):
    q = c.addons.order_by('collectionaddon__ordering')
    return list(q.values_list('id', flat=True))


def activitylog_count(type):
    qs = ActivityLog.objects
    if type:
        qs = qs.filter(action=type.id)
    return qs.count()


class TestCollections(test_utils.TestCase):
    fixtures = ('base/apps', 'base/users', 'base/addon_3615',
                'base/addon_10423_youtubesearch', 'base/addon_1833_yoono',
                'base/collections', 'bandwagon/test_models')

    def setUp(self):
        self.user = UserProfile.objects.create(username='uhhh', email='uh@hh')
        self.other = UserProfile.objects.exclude(id=self.user.id)[0]
        amo.set_user(self.user)

    def test_icon_url(self):

        # Has no icon
        c = Collection.objects.get(pk=512)
        assert c.icon_url.endswith('img/icons/collection.png')

        c.type = amo.COLLECTION_FAVORITES
        assert c.icon_url.endswith('img/icons/heart.png')

    def test_is_subscribed(self):
        c = Collection.objects.get(pk=512)
        c.following.create(user=self.user)
        assert c.is_subscribed(self.user)

    def test_translation_default(self):
        """Make sure we're getting strings from the default locale."""
        c = Collection.objects.get(pk=512)
        eq_(unicode(c.name), 'yay')

    def test_listed(self):
        """Make sure the manager's listed() filter works."""
        listed_count = Collection.objects.listed().count()
        # make a private collection
        private = Collection(
            name="Hello", uuid="4e2a1acc-39ae-47ec-956f-46e080ac7f69",
            listed=False, author=self.user)
        private.save()

        listed = Collection.objects.listed()
        eq_(len(listed), listed_count)

    def test_auto_uuid(self):
        c = Collection.objects.create(author=self.user)
        assert c.uuid != ''
        assert isinstance(c.uuid, basestring)

    def test_addon_index(self):
        c = Collection.objects.get(pk=80)
        c.author = self.user
        eq_(c.addon_index, None)
        ids = c.addons.values_list('id', flat=True)
        c.save()
        eq_(c.addon_index, Collection.make_index(ids))

    def test_recommended_collection(self):
        """RecommendedCollections automatically get type=rec."""
        c = RecommendedCollection.objects.create(author=self.user)
        eq_(c.type, amo.COLLECTION_RECOMMENDED)

    def test_set_addons(self):
        addons = list(Addon.objects.values_list('id', flat=True))
        c = Collection.objects.create(author=self.user)

        # Check insert.
        random.shuffle(addons)
        c.set_addons(addons)
        eq_(get_addons(c), addons)
        eq_(activitylog_count(amo.LOG.ADD_TO_COLLECTION), len(addons))

        # Check update.
        random.shuffle(addons)
        c.set_addons(addons)
        eq_(get_addons(c), addons)

        # Check delete.
        delete_cnt = len(addons) - 2
        addons = addons[:2]
        c.set_addons(addons)
        eq_(activitylog_count(amo.LOG.REMOVE_FROM_COLLECTION), delete_cnt)
        eq_(get_addons(c), addons)
        eq_(c.addons.count(), len(addons))

    def test_publishable_by(self):
        c = Collection.objects.create(author=self.other)
        CollectionUser(collection=c, user=self.user).save()
        eq_(c.publishable_by(self.user), True)

    def test_collection_meta(self):
        c = Collection.objects.create(author=self.user)
        eq_(c.addon_count, 0)
        c.add_addon(Addon.objects.all()[0])
        eq_(activitylog_count(amo.LOG.ADD_TO_COLLECTION), 1)
        c = Collection.objects.get(id=c.id)
        assert not c.from_cache
        eq_(c.addon_count, 1)

    def test_favorites_slug(self):
        c = Collection.objects.create(author=self.user, slug='favorites')
        eq_(c.type, amo.COLLECTION_NORMAL)
        eq_(c.slug, 'favorites~')

        c = Collection.objects.create(author=self.user, slug='favorites')
        eq_(c.type, amo.COLLECTION_NORMAL)
        eq_(c.slug, 'favorites~-1')

    def test_slug_dupe(self):
        c = Collection.objects.create(author=self.user, slug='boom')
        eq_(c.slug, 'boom')
        c.save()
        eq_(c.slug, 'boom')
        c = Collection.objects.create(author=self.user, slug='boom')
        eq_(c.slug, 'boom-1')
        c = Collection.objects.create(author=self.user, slug='boom')
        eq_(c.slug, 'boom-2')

    def test_watchers(self):
        def check(num):
            eq_(Collection.objects.get(id=512).subscribers, num)
        tasks.collection_watchers(512)
        check(0)
        CollectionWatcher.objects.create(collection_id=512, user=self.user)
        check(1)


class TestRecommendations(test_utils.TestCase):
    fixtures = ['base/addon-recs']
    ids = [5299, 1843, 2464, 7661, 5369]

    def setUp(self):
        self.user = UserProfile.objects.create(username='uhhh', email='uh@hh')
        amo.set_user(self.user)

    @classmethod
    def expected_recs(self):
        scores, ranked = [], {}
        # Get all the add-on => rank pairs.
        for x in AddonRecommendation.scores(self.ids).values():
            scores.extend(x.items())
        # Sum up any dupes.
        groups = itertools.groupby(sorted(scores), key=lambda x: x[0])
        for addon, pairs in groups:
            ranked[addon] = sum(x[1] for x in pairs)
        addons = sorted(ranked.items(), key=lambda x: x[1], reverse=True)
        return [x[0] for x in addons if x[0] not in self.ids]

    def test_build_recs(self):
        recs = RecommendedCollection.build_recs(self.ids)
        eq_(recs, self.expected_recs())

    @mock.patch('bandwagon.models.AddonRecommendation.scores')
    def test_no_dups(self, scores):
        # The inner dict is the recommended addons for addon 7.
        scores.return_value = {7: {1: 5, 2: 3, 3: 4}}
        recs = RecommendedCollection.build_recs([7, 3, 8])
        # 3 should not be in the list since we already have it.
        eq_(recs, [1, 2])


class TestFeaturedCollectionManager(test_utils.TestCase):
    fixtures = ['addons/featured', 'bandwagon/featured_collections',
                'base/addon_3615', 'base/collections', 'base/featured']

    def setUp(self):
        self.f = (lambda **kw: sorted(FeaturedCollection.objects
                                                        .addon_ids(**kw)))
        self.ids = [1001, 1003, 2464, 3481, 7661, 15679]
        self.default_ids = [1001, 1003, 2464, 7661, 15679]
        self.c = (lambda **kw: sorted(FeaturedCollection.objects
                                                        .creatured_ids(**kw)))

    def test_addon_ids_apps(self):
        eq_(self.f(), self.ids)
        eq_(self.f(app=amo.SUNBIRD), [])
        eq_(self.f(app=amo.FIREFOX), self.ids)

    def test_addon_ids_empty_locales(self):
        """
        Ensure that add-ons from featured collections without a locale are
        returned when filtering by a locale that contains no featured add-ons.
        """
        eq_(self.f(app=amo.FIREFOX, lang='en-US'), self.ids)
        # 3481 should not be in the French featured add-ons.
        eq_(self.f(app=amo.FIREFOX, lang='fr'), self.default_ids)

    def test_addon_ids_default_locale(self):
        """
        Ensure that add-ons from featured collections are filtered correctly
        by locale.
        """
        fc = FeaturedCollection.objects.get(id=1)
        fc.update(locale='fr')
        eq_(self.f(app=amo.FIREFOX), self.ids)  # Always contains all locales.
        eq_(self.f(app=amo.FIREFOX, lang='en-US'), [3481, 15679])
        # This should remain unchanged, since we include add-ons (15679) from
        # the default locale.
        eq_(self.f(app=amo.FIREFOX, lang='fr'), self.default_ids)

    def test_addons(self):
        ids = (lambda **kw:
            sorted(list(FeaturedCollection.objects.addons(**kw)
                                          .values_list('id', flat=True))))
        eq_(ids(), self.ids)
        eq_(ids(app=amo.FIREFOX), self.ids)
        eq_(ids(app=amo.FIREFOX, lang='en-US'), self.ids)
        eq_(ids(app=amo.FIREFOX, lang='fr'), self.default_ids)

    def test_creatured_ids(self):
        cat = Addon.objects.get(id=1001).categories.all()[0]
        expected = [(1001, cat.id, amo.FIREFOX.id, None)]
        eq_(self.c(), expected)
        eq_(self.c(category=999), [])
        eq_(self.c(category=cat.id, lang=None), expected)

        # This should contain creatured add-ons from the default locale.
        eq_(self.c(category=cat.id, lang='fr'), expected)

    def test_creatured_ids_new_addon_category(self):
        """Creatured add-ons should contain those add-ons in a category."""
        cat = Category.objects.all()[0]
        AddonCategory.objects.create(addon_id=1003, category=cat)
        eq_(self.c(), [(1001, cat.id, amo.FIREFOX.id, None),
                       (1003, cat.id, amo.FIREFOX.id, None)])

    def test_creatured_ids_remove_addon_category(self):
        """Creatured add-ons should disappear if no longer in a category."""
        AddonCategory.objects.filter(addon__id=1001)[0].delete()
        eq_(self.c(), [])

    def test_creatured_ids_new_locale_category(self):
        """Creatured add-ons should change if we change featured locale."""
        c = CollectionAddon.objects.create(addon_id=1003,
            collection=Collection.objects.create())
        FeaturedCollection.objects.create(locale='ja',
                                          application_id=amo.FIREFOX.id,
                                          collection=c.collection)
        cat = Category.objects.create(pk=12, slug='burr',
                                      type=amo.ADDON_EXTENSION,
                                      application_id=amo.FIREFOX.id)
        AddonCategory.objects.create(addon_id=1003, category=new_cat)

        # The 1003 is already featured for the default locale, so adding a
        # category for this add-on will give us two creatures.
        ja_creature = (1003, cat.id, amo.FIREFOX.id, 'ja')
        eq_(self.c(), [(1001, 22, amo.FIREFOX.id, None),
                       (1003, cat.id, amo.FIREFOX.id, None),
                       ja_creature])
        eq_(self.c(lang='ja'), [ja_creature])
        eq_(self.c(category=new_cat.id, lang='ja'), [ja_creature])
