from django.urls import reverse

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, reverse_ns, version_factory
from olympia.scanners.serializers import (
    PushScannerResultSerializer,
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


class TestPushScannerResultSerializer(TestCase):
    def setUp(self):
        super().setUp()
        self.version = version_factory(addon=addon_factory())
        self.valid_results = {'version': '1.0.0', 'matchedRules': []}

    def serialize(self, data):
        serializer = PushScannerResultSerializer(data=data)
        serializer.is_valid()
        return serializer

    def test_valid(self):
        serializer = self.serialize(
            {'version_id': self.version.pk, 'results': self.valid_results}
        )
        assert not serializer.errors
        assert serializer.validated_data['version_id'] == self.version.pk
        assert serializer.validated_data['results'] == self.valid_results

    def test_version_id_not_found(self):
        serializer = self.serialize(
            {'version_id': 999999, 'results': self.valid_results}
        )
        assert serializer.errors == {'version_id': ['Version not found.']}

    def test_missing_version_id(self):
        serializer = self.serialize({'results': self.valid_results})
        assert 'version_id' in serializer.errors

    def test_missing_results(self):
        serializer = self.serialize({'version_id': self.version.pk})
        assert 'results' in serializer.errors

    def test_results_missing_scanner_version(self):
        serializer = self.serialize(
            {'version_id': self.version.pk, 'results': {'matchedRules': []}}
        )
        assert 'results' in serializer.errors

    def test_results_missing_matched_rules(self):
        serializer = self.serialize(
            {'version_id': self.version.pk, 'results': {'version': '1.0.0'}}
        )
        assert 'results' in serializer.errors

    def test_results_extra_property_allowed(self):
        results = {'version': '1.0.0', 'matchedRules': [], 'unexpected': 'field'}
        serializer = self.serialize({'version_id': self.version.pk, 'results': results})
        assert not serializer.errors

    def test_results_with_valid_annotations(self):
        results = {
            'version': '1.0.0',
            'matchedRules': ['RULE_1'],
            'annotations': {'RULE_1': [{'message': 'found something'}]},
        }
        serializer = self.serialize({'version_id': self.version.pk, 'results': results})
        assert not serializer.errors

    def test_results_annotation_key_not_in_matched_rules(self):
        results = {
            'version': '1.0.0',
            'matchedRules': [],
            'annotations': {'UNKNOWN_RULE': [{'message': 'oops'}]},
        }
        serializer = self.serialize({'version_id': self.version.pk, 'results': results})
        assert 'results' in serializer.errors
        assert 'UNKNOWN_RULE' in serializer.errors['results'][0]

    def test_extra_top_level_field_not_allowed(self):
        serializer = self.serialize(
            {
                'version_id': self.version.pk,
                'results': self.valid_results,
                'unexpected': 'value',
            }
        )
        assert 'unexpected' in serializer.errors
