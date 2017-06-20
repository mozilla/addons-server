import datetime
import random

import mock

from olympia import amo, core
from olympia.amo.tests import TestCase
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.bandwagon.models import (
    Collection, CollectionAddon, CollectionUser, CollectionWatcher)
from olympia.bandwagon import tasks
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

    def test_is_subscribed(self):
        c = Collection(pk=512)
        c.following.create(user=self.user)
        assert c.is_subscribed(self.user)

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

    def test_publishable_by(self):
        c = Collection(pk=512, author=self.other)
        CollectionUser(collection=c, user=self.user).save()
        assert c.publishable_by(self.user)

    def test_manager_publishable_by(self):
        c1 = Collection.objects.create(author=self.user, name='B')
        c2 = Collection.objects.create(author=self.user, name='A')
        c3 = Collection.objects.create(author=self.other, name='D')
        c4 = Collection.objects.create(author=self.other, name='C')
        CollectionUser(collection=c1, user=self.user).save()
        CollectionUser(collection=c2, user=self.other).save()
        CollectionUser(collection=c3, user=self.user).save()
        CollectionUser(collection=c4, user=self.other).save()
        collections = Collection.objects.publishable_by(self.user)
        assert list(collections) == [c2, c1, c3]

    def test_collection_meta(self):
        c = Collection.objects.create(author=self.user)
        assert c.addon_count == 0
        c.add_addon(Addon.objects.all()[0])
        assert activitylog_count(amo.LOG.ADD_TO_COLLECTION) == 1
        c = Collection.objects.get(id=c.id)
        assert not c.from_cache
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

    def test_watchers(self):
        def check(num):
            assert Collection.objects.get(id=512).subscribers == num
        tasks.collection_watchers(512)
        check(0)
        CollectionWatcher.objects.create(collection_id=512, user=self.user)
        check(1)

    def test_can_view_stats(self):
        c = Collection.objects.create(author=self.user, slug='boom')

        fake_request = mock.Mock()

        # Owner.
        fake_request.user = self.user
        assert c.can_view_stats(fake_request)

        # Bad user.
        fake_request.user = UserProfile.objects.create(
            username='scrub', email='ez@dee')
        assert not c.can_view_stats(fake_request)

        # Member of group with Collections:Edit permission.
        group = Group.objects.create(name='Collections Agency',
                                     rules='CollectionStats:View')
        del fake_request.user.groups_list
        grouser = GroupUser.objects.create(user=fake_request.user, group=group)
        assert c.can_view_stats(fake_request)

        # Developer.
        grouser.delete()
        CollectionUser.objects.create(collection=c, user=self.user)
        fake_request.user = self.user
        assert c.can_view_stats(fake_request)


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
