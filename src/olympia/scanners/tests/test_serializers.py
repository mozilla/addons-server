from django.conf import settings
from django.urls import reverse

from olympia.addons.serializers import CompactLicenseSerializer, MinimalFileSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, reverse_ns, version_factory
from olympia.constants.scanners import YARA
from olympia.scanners.models import ScannerResult
from olympia.scanners.serializers import (
    ScannerResultSerializer,
    WebhookVersionSerializer,
)


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


class TestScannerResultSerializer(TestCase):
    def test_serialize(self):
        result = ScannerResult.objects.create(
            scanner=YARA, model_version='some.version'
        )
        data = ScannerResultSerializer(instance=result).data
        assert data == {
            'id': result.id,
            'scanner': result.get_scanner_name(),
            'label': None,
            'results': result.results,
            'created': result.created.strftime(
                settings.REST_FRAMEWORK['DATETIME_FORMAT']
            ),
            'model_version': result.model_version,
        }
