# -*- coding: utf-8 -*-
import mock
from rest_framework import serializers
from waffle.testutils import override_switch

from olympia.amo.tests import (
    BaseTestCase, addon_factory, collection_factory, TestCase, user_factory)
from olympia.bandwagon.models import CollectionAddon
from olympia.bandwagon.serializers import (
    CollectionAddonSerializer, CollectionAkismetSpamValidator,
    CollectionSerializer, CollectionWithAddonsSerializer)
from olympia.lib.akismet.models import AkismetReport


class TestCollectionAkismetSpamValidator(TestCase):
    def setUp(self):
        self.validator = CollectionAkismetSpamValidator(
            ('name', 'description'))
        serializer = mock.Mock()
        serializer.instance = collection_factory(
            name='name', description='Big Cheese')
        request = mock.Mock()
        request.user = user_factory()
        request.META = {}
        serializer.context = {'request': request}
        self.validator.set_context(serializer)
        self.data = {
            'name': {'en-US': 'Collection', 'fr': u'Collection'},
            'description': {'en-US': 'Big Cheese', 'fr': u'une gránd fromagé'},
            'random_data': {'en-US': 'to ignore'},
            'slug': 'cheese'}

    @override_switch('akismet-spam-check', active=False)
    @mock.patch('olympia.lib.akismet.models.AkismetReport.comment_check')
    def test_waffle_off(self, comment_check_mock):
        self.validator(self.data)

        # No Akismet checks
        assert AkismetReport.objects.count() == 0
        comment_check_mock.assert_not_called()

    @override_switch('akismet-spam-check', active=True)
    @mock.patch('olympia.lib.akismet.models.AkismetReport.comment_check')
    def test_ham(self, comment_check_mock):
        comment_check_mock.return_value = AkismetReport.HAM

        self.validator(self.data)

        # Akismet check is there
        assert AkismetReport.objects.count() == 2
        name_report = AkismetReport.objects.first()
        # name will only be there once because it's duplicated.
        assert name_report.comment_type == 'collection-name'
        assert name_report.comment == self.data['name']['en-US']
        summary_report = AkismetReport.objects.last()
        # en-US description won't be there because it's an existing description
        assert summary_report.comment_type == 'collection-description'
        assert summary_report.comment == self.data['description']['fr']

        assert comment_check_mock.call_count == 2

    @override_switch('akismet-spam-check', active=True)
    @mock.patch('olympia.lib.akismet.models.AkismetReport.comment_check')
    def test_spam(self, comment_check_mock):
        comment_check_mock.return_value = AkismetReport.MAYBE_SPAM

        with self.assertRaises(serializers.ValidationError):
            self.validator(self.data)

        # Akismet check is there
        assert AkismetReport.objects.count() == 2
        name_report = AkismetReport.objects.first()
        # name will only be there once because it's duplicated.
        assert name_report.comment_type == 'collection-name'
        assert name_report.comment == self.data['name']['en-US']
        summary_report = AkismetReport.objects.last()
        # en-US description won't be there because it's an existing description
        assert summary_report.comment_type == 'collection-description'
        assert summary_report.comment == self.data['description']['fr']

        # After the first comment_check was spam, additinal ones are skipped.
        assert comment_check_mock.call_count == 1


class TestCollectionSerializer(BaseTestCase):
    serializer = CollectionSerializer

    def setUp(self):
        super(TestCollectionSerializer, self).setUp()
        self.user = user_factory()
        self.collection = collection_factory()
        self.collection.update(author=self.user)

    def serialize(self):
        return self.serializer(self.collection).data

    def test_basic(self):
        data = self.serialize()
        assert data['id'] == self.collection.id
        assert data['uuid'] == self.collection.uuid
        assert data['name'] == {'en-US': self.collection.name}
        assert data['description'] == {'en-US': self.collection.description}
        assert data['url'] == self.collection.get_abs_url()
        assert data['addon_count'] == self.collection.addon_count
        assert data['modified'] == (
            self.collection.modified.replace(microsecond=0).isoformat() + 'Z')
        assert data['author']['id'] == self.user.id
        assert data['slug'] == self.collection.slug
        assert data['public'] == self.collection.listed
        assert data['default_locale'] == self.collection.default_locale


class TestCollectionAddonSerializer(BaseTestCase):

    def setUp(self):
        self.collection = collection_factory()
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)
        self.item = CollectionAddon.objects.get(addon=self.addon,
                                                collection=self.collection)
        self.item.comments = u'Dis is nice'
        self.item.save()

    def serialize(self):
        return CollectionAddonSerializer(self.item).data

    def test_basic(self):
        data = self.serialize()
        assert data['addon']['id'] == self.collection.addons.all()[0].id
        assert data['notes'] == {'en-US': self.item.comments}


class TestCollectionWithAddonsSerializer(TestCollectionSerializer):
    serializer = CollectionWithAddonsSerializer

    def setUp(self):
        super(TestCollectionWithAddonsSerializer, self).setUp()
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)

    def serialize(self):
        mock_viewset = mock.MagicMock()
        collection_addons = CollectionAddon.objects.filter(
            addon=self.addon, collection=self.collection)
        mock_viewset.get_addons_queryset.return_value = collection_addons
        return self.serializer(
            self.collection, context={'view': mock_viewset}).data

    def test_basic(self):
        super(TestCollectionWithAddonsSerializer, self).test_basic()
        collection_addon = CollectionAddon.objects.get(
            addon=self.addon, collection=self.collection)
        data = self.serialize()
        assert data['addons'] == [
            CollectionAddonSerializer(collection_addon).data
        ]
        assert data['addons'][0]['addon']['id'] == self.addon.id
