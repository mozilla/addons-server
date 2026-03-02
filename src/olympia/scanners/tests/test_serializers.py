from django.urls import reverse

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, reverse_ns, version_factory
from olympia.scanners.serializers import (
    WebhookAddonSerializer,
    WebhookVersionSerializer,
)


class TestWebhookAddonSerializer(TestCase):
    def test_serialize(self):
        addon = addon_factory()
        data = WebhookAddonSerializer(addon).data
        assert data.keys() == {
            'categories',
            'developer_comments',
            'id',
            'status',
            'homepage',
            'ratings',
            'is_featured',
            'last_updated',
            'is_disabled',
            'is_experimental',
            'has_eula',
            'name',
            'support_email',
            'support_url',
            'guid',
            'previews',
            'promoted',
            'type',
            'requires_payment',
            'average_daily_users',
            'url',
            'has_privacy_policy',
            'is_noindexed',
            'is_source_public',
            'weekly_downloads',
            'summary',
            'slug',
            'created',
            'default_locale',
            'tags',
            'description',
            'authors',
            'icons',
        }
        assert data['id'] == addon.id
        assert data['url'] == absolutify(
            reverse_ns('addon-detail', kwargs={'pk': addon.id})
        )
        for field in WebhookAddonSerializer.Meta.excluded_fields:
            assert field not in data

    def test_serialize_theme(self):
        addon = addon_factory(type=amo.ADDON_STATICTHEME)
        data = WebhookAddonSerializer(addon).data
        assert data['type'] == 'statictheme'


class TestWebhookVersionSerializer(TestCase):
    def setUp(self):
        super().setUp()

        self.version = version_factory(addon=addon_factory())

    def test_serialize(self):
        data = WebhookVersionSerializer(self.version).data
        assert data.keys() == {
            'license',
            'compatibility',
            'id',
            'release_notes',
            'reviewed',
            'channel',
            'is_strict_compatibility_enabled',
            'version',
            'file',
            'url',
            'download_source_url',
        }
        assert data['url'] == absolutify(
            reverse_ns(
                'addon-version-detail',
                kwargs={
                    'addon_pk': self.version.addon_id,
                    'pk': self.version.id,
                },
            )
        )
        for field in WebhookVersionSerializer.Meta.excluded_fields:
            assert field not in data

    def test_download_source_url_without_source(self):
        assert not self.version.sources_provided
        data = WebhookVersionSerializer(self.version).data
        assert data['download_source_url'] is None

    def test_download_source_url_with_source(self):
        self.version.update(source='/path/to/source.zip')
        assert self.version.sources_provided
        data = WebhookVersionSerializer(self.version).data
        assert data['download_source_url'] == absolutify(
            reverse('downloads.source', kwargs={'version_id': self.version.id})
        )
