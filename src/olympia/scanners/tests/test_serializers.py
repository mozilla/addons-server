from django.urls import reverse

from olympia import amo
from olympia.addons.serializers import CompactLicenseSerializer, MinimalFileSerializer
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
        assert data == {
            'id': addon.id,
            'type': 'extension',
        }

    def test_serialize_theme(self):
        addon = addon_factory(type=amo.ADDON_STATICTHEME)
        data = WebhookAddonSerializer(addon).data
        assert data == {
            'id': addon.id,
            'type': 'statictheme',
        }


class TestWebhookVersionSerializer(TestCase):
    def setUp(self):
        super().setUp()

        self.version = version_factory(addon=addon_factory())

    def test_serialize(self):
        data = WebhookVersionSerializer(self.version).data
        assert data == {
            'id': self.version.id,
            'version': self.version.version,
            'file': MinimalFileSerializer(self.version.file).data,
            'license': CompactLicenseSerializer(self.version.license).data,
            'url': absolutify(
                reverse_ns(
                    'addon-version-detail',
                    kwargs={
                        'addon_pk': self.version.addon_id,
                        'pk': self.version.id,
                    },
                )
            ),
            'download_source_url': None,
        }

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
