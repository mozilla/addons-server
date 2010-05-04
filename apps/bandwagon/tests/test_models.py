import itertools
import random

from nose.tools import eq_
import test_utils

import amo
from addons.models import Addon, AddonRecommendation
from bandwagon.models import (Collection, SyncedCollection,
                              RecommendedCollection)


class TestCollections(test_utils.TestCase):
    fixtures = ['base/addons', 'bandwagon/test_models', 'base/collections']

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

        def get_addons():
            q = c.addons.order_by('collectionaddon__ordering')
            return list(q.values_list('id', flat=True))

        # Check insert.
        random.shuffle(addons)
        c.set_addons(addons)
        eq_(get_addons(), addons)

        # Check update.
        random.shuffle(addons)
        c.set_addons(addons)
        eq_(get_addons(), addons)

        # Check delete.
        addons = addons[:2]
        c.set_addons(addons)
        eq_(get_addons(), addons)
        eq_(c.addons.count(), len(addons))


class TestRecommendations(test_utils.TestCase):
    fixtures = ['base/addon-recs']

    def test_get_recs(self):
        ids = [5299, 1843, 2464, 7661, 5369]
        scores, ranked = [], {}
        # Get all the add-on => rank pairs.
        for x in AddonRecommendation.scores(ids).values():
            scores.extend(x.items())
        # Sum up any dupes.
        groups = itertools.groupby(sorted(scores), key=lambda x: x[0])
        for addon, pairs in groups:
            ranked[addon] = sum(x[1] for x in pairs)
        addons = sorted(ranked.items(), key=lambda x: x[1])

        recs = RecommendedCollection.get_recs(ids)
        eq_(recs, [x[0] for x in addons])
