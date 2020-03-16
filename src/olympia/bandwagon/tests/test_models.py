import uuid
from unittest import mock

from django.conf import settings

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.tests import addon_factory, TestCase
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
        assert str(c.description) == '&lt;b&gt;foo&lt;/b&gt; some text'

    def test_translation_default(self):
        """Make sure we're getting strings from the default locale."""
        c = Collection.objects.get(pk=512)
        assert str(c.name) == 'yay'

    def test_listed(self):
        """Make sure the manager's listed() filter works."""
        listed_count = Collection.objects.listed().count()
        # Make a private collection.
        Collection.objects.create(
            name='Hello', uuid='4e2a1acc39ae47ec956f46e080ac7f69',
            listed=False, author=self.user)

        assert Collection.objects.listed().count() == listed_count

    def test_auto_uuid(self):
        c = Collection.objects.create(author=self.user)
        assert c.uuid
        assert isinstance(c.uuid, uuid.UUID)

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

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    def test_add_addon_reindex(self, index_addons_mock):
        collection = Collection.objects.create(author=self.user, slug='foo')
        addon = addon_factory()
        index_addons_mock.reset_mock()
        collection.add_addon(addon)
        assert index_addons_mock.call_count == 0

        collection = Collection.objects.create(
            author=self.user, slug='featured',
            id=settings.COLLECTION_FEATURED_THEMES_ID)
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
            author=self.user, slug='featured',
            id=settings.COLLECTION_FEATURED_THEMES_ID)
        addon_featured = addon_factory()
        collection.add_addon(addon_featured)
        index_addons_mock.reset_mock()

        collection.remove_addon(addon_featured)
        assert collection.addons.count() == 0
        assert index_addons_mock.call_count == 1
        assert index_addons_mock.call_args[0] == ([addon_featured.pk],)


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
