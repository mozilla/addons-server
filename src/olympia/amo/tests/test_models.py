from datetime import datetime

import pytest
from mock import Mock

from django.core.files.storage import default_storage as storage

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo import models as amo_models
from olympia.amo.tests import TestCase
from olympia.users.models import UserProfile
from olympia.zadmin.models import SiteEvent


pytestmark = pytest.mark.django_db


class ManualOrderTest(TestCase):
    fixtures = ('base/addon_3615', 'base/addon_5299_gcal', 'base/addon_40')

    def test_ordering(self):
        """Given a specific set of primary keys, assure that we return addons
        in that order."""

        semi_arbitrary_order = [40, 5299, 3615]
        addons = amo_models.manual_order(
            Addon.objects.all(), semi_arbitrary_order)
        assert semi_arbitrary_order == [addon.id for addon in addons]


def test_use_primary_db():
    local = amo_models.multidb.pinning._locals
    assert not getattr(local, 'pinned', False)
    with amo_models.use_primary_db():
        assert local.pinned
        with amo_models.use_primary_db():
            assert local.pinned
        assert local.pinned
    assert not local.pinned


class TestModelBase(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestModelBase, self).setUp()
        self.saved_cb = amo_models._on_change_callbacks.copy()
        amo_models._on_change_callbacks.clear()
        self.cb = Mock()
        self.cb.__name__ = 'testing_mock_callback'
        Addon.on_change(self.cb)

    def tearDown(self):
        amo_models._on_change_callbacks = self.saved_cb
        super(TestModelBase, self).tearDown()

    def test_multiple_ignored(self):
        cb = Mock()
        cb.__name__ = 'something'
        old = len(amo_models._on_change_callbacks[Addon])
        Addon.on_change(cb)
        assert len(amo_models._on_change_callbacks[Addon]) == old + 1
        Addon.on_change(cb)
        assert len(amo_models._on_change_callbacks[Addon]) == old + 1

    def test_change_called_on_new_instance_save(self):
        for create_addon in (Addon, Addon.objects.create):
            addon = create_addon(public_stats=False, type=amo.ADDON_EXTENSION)
            addon.public_stats = True
            addon.save()
            assert self.cb.called
            kw = self.cb.call_args[1]
            assert not kw['old_attr']['public_stats']
            assert kw['new_attr']['public_stats']
            assert kw['instance'].id == addon.id
            assert kw['sender'] == Addon

    def test_change_called_on_update(self):
        addon = Addon.objects.get(pk=3615)
        addon.update(external_software=False)
        assert self.cb.called
        kw = self.cb.call_args[1]
        assert kw['old_attr']['external_software']
        assert not kw['new_attr']['external_software']
        assert kw['instance'].id == addon.id
        assert kw['sender'] == Addon

    def test_change_called_on_save(self):
        addon = Addon.objects.get(pk=3615)
        addon.external_software = False
        addon.save()
        assert self.cb.called
        kw = self.cb.call_args[1]
        assert kw['old_attr']['external_software']
        assert not kw['new_attr']['external_software']
        assert kw['instance'].id == addon.id
        assert kw['sender'] == Addon

    def test_change_is_not_recursive(self):

        class fn:
            called = False

        def callback(old_attr=None, new_attr=None, instance=None,
                     sender=None, **kw):
            fn.called = True
            # Both save and update should be protected:
            instance.update(public_stats=True)
            instance.save()

        Addon.on_change(callback)

        addon = Addon.objects.get(pk=3615)
        assert not addon.public_stats
        addon.save()
        assert fn.called
        # No exception = pass

    def test_get_or_create_read_committed(self):
        """Test get_or_create behavior.

        This test originally tested our own `safer_get_or_create` method
        but since we switched to using 'read committed' isolation level
        Djangos builtin `get_or_create` works perfectly for us now.
        """
        data = {'guid': '123', 'type': amo.ADDON_EXTENSION}
        a, c = Addon.objects.get_or_create(**data)
        assert c
        b, c = Addon.objects.get_or_create(**data)
        assert not c
        assert a == b

    def test_reload(self):
        # Make it an extension.
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        addon.save()

        # Make it a persona.
        Addon.objects.get(id=addon.id).update(type=amo.ADDON_PERSONA)

        # Still an extension.
        assert addon.type == amo.ADDON_EXTENSION

        # Reload. And it's magically now a persona.
        assert addon.reload().type == amo.ADDON_PERSONA
        assert addon.type == amo.ADDON_PERSONA

    def test_get_unfiltered_manager(self):
        Addon.get_unfiltered_manager() == Addon.unfiltered
        UserProfile.get_unfiltered_manager() == UserProfile.objects


class BasePreviewMixin(object):

    def get_object(self):
        raise NotImplementedError

    def test_filename(self):
        preview = self.get_object()
        assert preview.thumbnail_path.endswith('.png')
        assert preview.image_path.endswith('.png')
        assert preview.original_path.endswith('.png')

    def test_filename_in_url(self):
        preview = self.get_object()
        assert '.png?modified=' in preview.thumbnail_url
        assert '.png?modified=' in preview.image_url

    def check_delete(self, preview, filename):
        """
        Test that when the Preview object is deleted, its image, thumb, and
        original are deleted from the filesystem.
        """
        try:
            with storage.open(filename, 'w') as f:
                f.write('sample data\n')
            assert storage.exists(filename)
            preview.delete()
            assert not storage.exists(filename)
        finally:
            if storage.exists(filename):
                storage.delete(filename)

    def test_delete_image(self):
        preview = self.get_object()
        self.check_delete(preview, preview.image_path)

    def test_delete_thumbnail(self):
        preview = self.get_object()
        self.check_delete(preview, preview.thumbnail_path)

    def test_delete_original(self):
        preview = self.get_object()
        self.check_delete(preview, preview.original_path)


class BaseQuerysetTestCase(TestCase):
    def test_queryset_transform(self):
        # We test with the SiteEvent model because it's a simple model
        # with no translated fields, no caching or other fancy features.
        SiteEvent.objects.create(start=datetime.now(), description='Zero')
        first = SiteEvent.objects.create(start=datetime.now(),
                                         description='First')
        second = SiteEvent.objects.create(start=datetime.now(),
                                          description='Second')
        SiteEvent.objects.create(start=datetime.now(), description='Third')
        SiteEvent.objects.create(start=datetime.now(), description='')

        seen_by_first_transform = []
        seen_by_second_transform = []
        with self.assertNumQueries(0):
            # No database hit yet, everything is still lazy.
            qs = amo_models.BaseQuerySet(SiteEvent)
            qs = qs.exclude(description='').order_by('id')[1:3]
            qs = qs.transform(
                lambda items: seen_by_first_transform.extend(list(items)))
            qs = qs.transform(
                lambda items: seen_by_second_transform.extend(
                    list(reversed(items))))
        with self.assertNumQueries(1):
            assert list(qs) == [first, second]
        # Check that each transform function was hit correctly, once.
        assert seen_by_first_transform == [first, second]
        assert seen_by_second_transform == [second, first]
