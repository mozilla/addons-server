import itertools
import random

from nose.tools import eq_
import test_utils

import amo
from addons.models import Addon, AddonRecommendation
from bandwagon.models import (Collection, SyncedCollection,
                              RecommendedCollection)
import settings
from users.models import UserProfile


def get_addons(c):
    q = c.addons.order_by('collectionaddon__ordering')
    return list(q.values_list('id', flat=True))


class TestCollections(test_utils.TestCase):
    fixtures = ['base/fixtures', 'bandwagon/test_models']

    def test_unicode(self):
        c = Collection.objects.get(pk=512)
        eq_(unicode(c), 'yay (4)')

    def test_icon_url(self):
        c = Collection.objects.get(pk=512)
        eq_(settings.MEDIA_URL + 'img/amo2009/icons/collection.png',
            c.icon_url)

    def test_author(self):
        c = Collection.objects.get(pk=80)
        eq_(c.author, UserProfile.objects.get(pk=10482))

    def test_is_subscribed(self):
        c = Collection.objects.get(pk=512)
        u = UserProfile()
        u.nickname='unique'
        u.save()
        c.subscriptions.create(user=u)
        assert c.is_subscribed(u), "User isn't subscribed to collection."

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
            listed=False)
        private.save()

        listed = Collection.objects.listed()
        eq_(len(listed), listed_count)

    def test_auto_uuid(self):
        c = Collection.objects.create()
        assert c.uuid != ''
        assert isinstance(c.uuid, basestring)

    def test_addon_index(self):
        c = Collection.objects.get(pk=5)
        eq_(c.addon_index, None)
        ids = c.addons.values_list('id', flat=True)
        c.save()
        eq_(c.addon_index, Collection.make_index(ids))

    def test_synced_collection(self):
        """SyncedCollections automatically get type=sync."""
        c = SyncedCollection.objects.create()
        eq_(c.type, amo.COLLECTION_SYNCHRONIZED)

    def test_recommended_collection(self):
        """RecommendedCollections automatically get type=rec."""
        c = RecommendedCollection.objects.create()
        eq_(c.type, amo.COLLECTION_RECOMMENDED)

    def test_set_addons(self):
        addons = list(Addon.objects.values_list('id', flat=True))
        c = Collection.objects.create()

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


class TestRecommendations(test_utils.TestCase):
    fixtures = ['base/addon-recs']
    ids = [5299, 1843, 2464, 7661, 5369]

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
        c = Collection.objects.create()
        c.set_addons(self.ids)
        recs = c.get_recommendations()
        eq_(recs.type, amo.COLLECTION_RECOMMENDED)
        eq_(recs.listed, False)
        expected = self.expected_recs()[:Collection.RECOMMENDATION_LIMIT]
        eq_(get_addons(recs), expected)
