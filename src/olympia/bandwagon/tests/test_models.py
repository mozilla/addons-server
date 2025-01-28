import uuid
from unittest import mock

from django.conf import settings

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory
from olympia.bandwagon.models import Collection
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
    fixtures = ('base/addon_3615', 'bandwagon/test_models', 'base/user_4043307')

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.create(username='uhhh', email='uh@hh')
        self.other = UserProfile.objects.exclude(id=self.user.id)[0]
        core.set_user(self.user)

    def test_description(self):
        collection = Collection.objects.create(
            description='<a href="http://example.com">example.com</a> '
            'http://example.com <b>foo</b> some text lol.com'
        )
        # Escapes all HTML.
        assert (
            str(collection.description)
            == '&lt;a href="  &lt;b&gt;foo&lt;/b&gt; some text lol.com'
        )

    def test_translation_default(self):
        """Make sure we're getting strings from the default locale."""
        c = Collection.objects.get(pk=512)
        assert str(c.name) == 'yay'

    def test_auto_uuid(self):
        c = Collection.objects.create(author=self.user)
        assert c.uuid
        assert isinstance(c.uuid, uuid.UUID)

    def test_collection_meta(self):
        # Create a collection, making sure modified date is set in the past.
        some_time_ago = self.days_ago(442)
        collection = Collection.objects.create(author=self.user)
        collection.update(modified=some_time_ago, _signal=False)
        # Double check initial state just to be sure.
        assert collection.addon_count == 0
        self.assertCloseToNow(collection.modified, now=some_time_ago)

        # Add an add-on and check the result.
        collection.add_addon(Addon.objects.all()[0])
        assert activitylog_count(amo.LOG.ADD_TO_COLLECTION) == 1
        collection.reload()
        assert collection.addon_count == 1
        self.assertCloseToNow(collection.modified)

        # Now remove it and check again.
        collection.update(modified=some_time_ago, _signal=False)
        collection.remove_addon(Addon.objects.all()[0])
        collection.reload()
        assert collection.addon_count == 0
        self.assertCloseToNow(collection.modified)

    def test_slug_dupe(self):
        c = Collection.objects.create(author=self.user, slug='boom')
        assert c.slug == 'boom'
        c.save()
        assert c.slug == 'boom'
        c = Collection.objects.create(author=self.user, slug='boom')
        assert c.slug == 'boom-1'
        c = Collection.objects.create(author=self.user, slug='boom')
        assert c.slug == 'boom-2'

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    def test_add_addon_reindex(self, index_addons_mock):
        collection = Collection.objects.create(author=self.user, slug='foo')
        addon = addon_factory()
        index_addons_mock.reset_mock()
        collection.add_addon(addon)
        assert index_addons_mock.call_count == 0

        collection = Collection.objects.create(
            author=self.user, slug='featured', id=settings.COLLECTION_FEATURED_THEMES_ID
        )
        addon_featured = addon_factory()
        index_addons_mock.reset_mock()

        collection.add_addon(addon_featured)
        assert collection.addons.count() == 1
        assert index_addons_mock.call_count == 1
        assert index_addons_mock.call_args[0] == ([addon_featured.pk],)

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    def test_remove_addon_reindex(self, index_addons_mock):
        collection = Collection.objects.create(author=self.user, slug='foo')
        addon = addon_factory()
        collection.add_addon(addon)
        index_addons_mock.reset_mock()

        collection.remove_addon(addon)
        assert index_addons_mock.call_count == 0

        collection = Collection.objects.create(
            author=self.user, slug='featured', id=settings.COLLECTION_FEATURED_THEMES_ID
        )
        addon_featured = addon_factory()
        collection.add_addon(addon_featured)
        index_addons_mock.reset_mock()

        collection.remove_addon(addon_featured)
        assert collection.addons.count() == 0
        assert index_addons_mock.call_count == 1
        assert index_addons_mock.call_args[0] == ([addon_featured.pk],)

    def test_delete(self):
        collection = Collection.objects.get(pk=512)
        slug = collection.slug
        collection.delete()

        assert not Collection.objects.all().exists()
        assert Collection.unfiltered.all().exists()
        # slug is cleared
        assert collection.reload().slug is None
        assert collection.deleted

        another = Collection(author=self.user, slug=slug)
        another.save()
        assert another.reload().slug == slug

        another.delete(clear_slug=False)
        assert not Collection.objects.all().exists()
        assert Collection.unfiltered.all().exists()
        # not if clear_slug=False
        assert another.reload().slug == slug

        # so if another collection tries to use that slug it will be fixed
        yet_another = Collection(author=self.user, slug=slug)
        yet_another.save()
        assert yet_another.reload().slug == f'{slug}-1'

    def test_delete_hard(self):
        collection = Collection.objects.get(pk=512)
        # If hard_delete the instance is gone
        collection.delete(hard=True)
        assert not Collection.objects.all().exists()
        assert not Collection.unfiltered.all().exists()

    def test_undelete(self):
        collection = Collection.objects.get(pk=512)
        collection.update(slug=None, deleted=True)

        collection.undelete()
        collection.reload()
        assert not collection.deleted
        # if collection had no slug (it was cleared during a delete) then generate one
        assert collection.slug is not None

    def test_delete_queryset(self):
        collection = Collection.objects.get(pk=512)
        original_slug = collection.slug
        assert original_slug
        Collection.objects.filter(pk=collection.pk).delete()
        collection.reload()
        assert collection.deleted
        assert collection.slug == original_slug

    def test_undelete_queryset(self):
        collection = Collection.objects.get(pk=512)
        collection.delete()
        assert collection.deleted

        Collection.unfiltered.filter(pk=collection.pk).undelete()
        collection.reload()
        assert not collection.deleted
