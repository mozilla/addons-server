import itertools
import random

from nose.tools import eq_
import test_utils

import amo
from addons.models import Addon, AddonRecommendation
from bandwagon.models import (Collection, CollectionUser, CollectionWatcher,
                              SyncedCollection, RecommendedCollection)
from bandwagon import tasks
from users.models import UserProfile


def get_addons(c):
    q = c.addons.order_by('collectionaddon__ordering')
    return list(q.values_list('id', flat=True))


class TestCollections(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'base/collections', 'bandwagon/test_models']

    def setUp(self):
        self.user = UserProfile.objects.create(username='uhhh', email='uh@hh')
        self.other = UserProfile.objects.exclude(id=self.user.id)[0]

    def test_icon_url(self):

        # Has no icon
        c = Collection.objects.get(pk=512)
        assert c.icon_url.endswith('img/amo2009/icons/collection.png')

        c.type = amo.COLLECTION_FAVORITES
        assert c.icon_url.endswith('img/amo2009/icons/heart.png')

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

    def test_synced_collection(self):
        """SyncedCollections automatically get type=sync."""
        c = SyncedCollection.objects.create(author=self.user)
        eq_(c.type, amo.COLLECTION_SYNCHRONIZED)

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

        # Check update.
        random.shuffle(addons)
        c.set_addons(addons)
        eq_(get_addons(c), addons)

        # Check delete.
        addons = addons[:2]
        c.set_addons(addons)
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

    def expected_recs(self):
        scores, ranked = [], {}
        # Get all the add-on => rank pairs.
        for x in AddonRecommendation.scores(self.ids).values():
            scores.extend(x.items())
        # Sum up any dupes.
        groups = itertools.groupby(sorted(scores), key=lambda x: x[0])
        for addon, pairs in groups:
            ranked[addon] = sum(x[1] for x in pairs)
        addons = sorted(ranked.items(), key=lambda x: x[1])
        return [x[0] for x in addons]

    def test_build_recs(self):
        recs = RecommendedCollection.build_recs(self.ids)
        eq_(recs, self.expected_recs())

    def test_get_recommendations(self):
        c = Collection.objects.create(author=self.user)
        c.set_addons(self.ids)
        recs = c.get_recommendations()
        eq_(recs.type, amo.COLLECTION_RECOMMENDED)
        eq_(recs.listed, False)
        expected = self.expected_recs()[:Collection.RECOMMENDATION_LIMIT]
        eq_(get_addons(recs), expected)

        # Test that we're getting the same recommendations.
        recs2 = c.get_recommendations()
        eq_(recs, recs2)
