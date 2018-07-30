import datetime
import random

import mock

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory, collection_factory
from olympia.bandwagon.models import (
    Collection, CollectionAddon, FeaturedCollection)
from olympia.users.models import UserProfile


def get_addons(c):
    q = c.addons.order_by('collectionaddon__ordering')
    return list(q.values_list('id', flat=True))


def activitylog_count(type):
    qs = ActivityLog.objects
    if type:
        qs = qs.filter(action=type.id)
    return qs.count()


class TestCollections(TestCase):
    fixtures = ('base/addon_3615', 'bandwagon/test_models',
                'base/user_4043307')

    def setUp(self):
        super(TestCollections, self).setUp()
        self.user = UserProfile.objects.create(username='uhhh', email='uh@hh')
        self.other = UserProfile.objects.exclude(id=self.user.id)[0]
        core.set_user(self.user)

    def test_description(self):
        c = Collection.objects.create(
            description='<a href="http://example.com">example.com</a> '
                        'http://example.com <b>foo</b> some text')
        # All markup escaped, links are stripped.
        assert unicode(c.description) == '&lt;b&gt;foo&lt;/b&gt; some text'

    def test_icon_url(self):
        # Has no icon.
        c = Collection(pk=512, modified=datetime.datetime.now())
        assert c.icon_url.endswith('img/icons/collection.png')

        c.icontype = 'image/png'
        url = c.icon_url.split('?')[0]
        assert url.endswith('0/512.png')

        c.id = 12341234
        url = c.icon_url.split('?')[0]
        assert url.endswith('12341/12341234.png')

        c.icontype = None
        c.type = amo.COLLECTION_FAVORITES
        assert c.icon_url.endswith('img/icons/heart.png')

    def test_translation_default(self):
        """Make sure we're getting strings from the default locale."""
        c = Collection.objects.get(pk=512)
        assert unicode(c.name) == 'yay'

    def test_listed(self):
        """Make sure the manager's listed() filter works."""
        listed_count = Collection.objects.listed().count()
        # Make a private collection.
        Collection.objects.create(
            name="Hello", uuid="4e2a1acc-39ae-47ec-956f-46e080ac7f69",
            listed=False, author=self.user)

        assert Collection.objects.listed().count() == listed_count

    def test_auto_uuid(self):
        c = Collection.objects.create(author=self.user)
        assert c.uuid != ''
        assert isinstance(c.uuid, basestring)

    def test_set_addons(self):
        addons = list(Addon.objects.values_list('id', flat=True))
        c = Collection.objects.create(author=self.user)

        # Check insert.
        random.shuffle(addons)
        c.set_addons(addons)
        assert get_addons(c) == addons
        assert activitylog_count(amo.LOG.ADD_TO_COLLECTION) == len(addons)

        # Check update.
        random.shuffle(addons)
        c.set_addons(addons)
        assert get_addons(c) == addons

        # Check delete.
        delete_cnt = len(addons) - 1
        addons = addons[:2]
        c.set_addons(addons)
        assert activitylog_count(amo.LOG.REMOVE_FROM_COLLECTION) == delete_cnt
        assert get_addons(c) == addons
        assert c.addons.count() == len(addons)

    def test_set_addons_comment(self):
        addons = list(Addon.objects.values_list('id', flat=True))
        c = Collection.objects.create(author=self.user)

        c.set_addons(addons, {addons[0]: 'This is a comment.'})
        collection_addon = CollectionAddon.objects.get(collection=c,
                                                       addon=addons[0])
        assert collection_addon.comments == 'This is a comment.'

    def test_collection_meta(self):
        c = Collection.objects.create(author=self.user)
        assert c.addon_count == 0
        c.add_addon(Addon.objects.all()[0])
        assert activitylog_count(amo.LOG.ADD_TO_COLLECTION) == 1
        c = Collection.objects.get(id=c.id)
        assert c.addon_count == 1

    def test_favorites_slug(self):
        c = Collection.objects.create(author=self.user, slug='favorites')
        assert c.type == amo.COLLECTION_NORMAL
        assert c.slug == 'favorites~'

        c = Collection.objects.create(author=self.user, slug='favorites')
        assert c.type == amo.COLLECTION_NORMAL
        assert c.slug == 'favorites~-1'

    def test_slug_dupe(self):
        c = Collection.objects.create(author=self.user, slug='boom')
        assert c.slug == 'boom'
        c.save()
        assert c.slug == 'boom'
        c = Collection.objects.create(author=self.user, slug='boom')
        assert c.slug == 'boom-1'
        c = Collection.objects.create(author=self.user, slug='boom')
        assert c.slug == 'boom-2'


class TestCollectionQuerySet(TestCase):
    fixtures = ('base/addon_3615',)

    def test_with_has_addon(self):
        user = UserProfile.objects.create(username='uhhh', email='uh@hh')
        collection = Collection.objects.create(author=user)
        addon = Addon.objects.all()[0]

        qset = (
            Collection.objects
            .filter(pk=collection.id)
            .with_has_addon(addon.id))

        assert not qset.first().has_addon

        collection.add_addon(addon)

        assert qset.first().has_addon


class TestFeaturedCollectionSignals(TestCase):
    """The signal needs to fire for all cases when Addon.is_featured would
    potentially change."""
    MOCK_TARGET = 'olympia.bandwagon.models.Collection.update_featured_status'

    def setUp(self):
        super(TestFeaturedCollectionSignals, self).setUp()
        self.collection = collection_factory()
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)

    def test_update_featured_status_does_index_addons(self):
        from olympia.addons.tasks import index_addons

        extra_addon = addon_factory()

        # Make sure index_addons is a mock, and then clear it.
        assert index_addons.delay.call_count
        index_addons.delay.reset_mock()

        # Featuring the collection indexes the add-ons in it.
        FeaturedCollection.objects.create(
            collection=self.collection,
            application=self.collection.application)
        assert index_addons.delay.call_count == 1
        index_addons.delay.call_args[0] == ([self.addon.pk],)
        index_addons.delay.reset_mock()

        # Adding an add-on re-indexes all add-ons in the collection
        # (we're not smart enough to know it's only necessary to do it for
        # the one we just added and not the rest).
        self.collection.add_addon(extra_addon)
        assert index_addons.delay.call_count == 1
        index_addons.delay.call_args[0] == ([self.addon.pk, extra_addon.pk],)
        index_addons.delay.reset_mock()

        # Removing an add-on needs 2 calls: one to reindex the add-ons that
        # are still in the collection (again, we're not smart enough to realize
        # it's not necessary) and one to reindex the add-on that has been
        # removed.
        self.collection.remove_addon(extra_addon)
        assert index_addons.delay.call_count == 2
        index_addons.delay.call_args[0] == ([self.addon.pk],)
        index_addons.delay.call_args[1] == ([extra_addon.pk],)

    def test_addon_added_to_featured_collection(self):
        FeaturedCollection.objects.create(
            collection=self.collection,
            application=self.collection.application)

        with mock.patch(self.MOCK_TARGET) as function_mock:
            self.collection.add_addon(addon_factory())
            function_mock.assert_called()

    def test_addon_removed_from_featured_collection(self):
        addon = addon_factory()
        self.collection.add_addon(addon)
        FeaturedCollection.objects.create(
            collection=self.collection,
            application=self.collection.application)

        with mock.patch(self.MOCK_TARGET) as function_mock:
            self.collection.remove_addon(addon)
            function_mock.assert_called()

    def test_featured_collection_deleted(self):
        FeaturedCollection.objects.create(
            collection=self.collection,
            application=self.collection.application)

        with mock.patch(self.MOCK_TARGET) as function_mock:
            self.collection.delete()
            function_mock.assert_called()

    def test_collection_becomes_featured(self):
        with mock.patch(self.MOCK_TARGET) as function_mock:
            FeaturedCollection.objects.create(
                collection=self.collection,
                application=self.collection.application)
            function_mock.assert_called()

    def test_collection_stops_being_featured(self):
        featured = FeaturedCollection.objects.create(
            collection=self.collection,
            application=self.collection.application)

        with mock.patch(self.MOCK_TARGET) as function_mock:
            featured.delete()
            function_mock.assert_called()

    def test_signal_only_with_featured(self):
        with mock.patch(self.MOCK_TARGET) as function_mock:
            addon = addon_factory()
            collection = collection_factory()
            collection.add_addon(addon)
            collection.remove_addon(addon)
            collection.delete()
            function_mock.assert_not_called()
