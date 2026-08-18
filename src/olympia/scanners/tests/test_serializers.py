from django.urls import reverse

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, reverse_ns, version_factory
from olympia.constants.scanners import (
    NARC,
    NARC_RULE_CONFIGURATION_SCHEMA,
    NEW,
    RUNNING,
    YARA,
)
from olympia.scanners.models import ScannerQueryResult, ScannerQueryRule
from olympia.scanners.serializers import (
    PatchScannerResultSerializer,
    PushScannerResultSerializer,
    ScannerQueryResultSerializer,
    ScannerQueryRuleSerializer,
    WebhookAddonSerializer,
    WebhookVersionSerializer,
)
from olympia.scanners.utils import default_from_schema


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

    def test_results_annotation_value_not_an_array(self):
        results = {
            'version': '1.0.0',
            'matchedRules': ['RULE_1'],
            'annotations': {'RULE_1': {'message': 'not an array'}},
        }
        serializer = self.serialize({'version_id': self.version.pk, 'results': results})
        assert 'results' in serializer.errors

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


class TestPatchScannerResultSerializer(TestCase):
    def setUp(self):
        super().setUp()
        self.valid_results = {'version': '1.0.0', 'matchedRules': []}

    def serialize(self, data):
        serializer = PatchScannerResultSerializer(data=data)
        serializer.is_valid()
        return serializer

    def test_valid(self):
        serializer = self.serialize({'results': self.valid_results})
        assert not serializer.errors
        assert serializer.validated_data['results'] == self.valid_results

    def test_missing_results(self):
        serializer = self.serialize({})
        assert 'results' in serializer.errors

    def test_results_missing_scanner_version(self):
        serializer = self.serialize({'results': {'matchedRules': []}})
        assert 'results' in serializer.errors

    def test_results_missing_matched_rules(self):
        serializer = self.serialize({'results': {'version': '1.0.0'}})
        assert 'results' in serializer.errors

    def test_results_extra_property_allowed(self):
        results = {'version': '1.0.0', 'matchedRules': [], 'unexpected': 'field'}
        serializer = self.serialize({'results': results})
        assert not serializer.errors

    def test_results_with_valid_annotations(self):
        results = {
            'version': '1.0.0',
            'matchedRules': ['RULE_1'],
            'annotations': {'RULE_1': [{'message': 'found something'}]},
        }
        serializer = self.serialize({'results': results})
        assert not serializer.errors

    def test_results_annotation_value_not_an_array(self):
        results = {
            'version': '1.0.0',
            'matchedRules': ['RULE_1'],
            'annotations': {'RULE_1': {'message': 'not an array'}},
        }
        serializer = self.serialize({'results': results})
        assert 'results' in serializer.errors

    def test_results_annotation_key_not_in_matched_rules(self):
        results = {
            'version': '1.0.0',
            'matchedRules': [],
            'annotations': {'UNKNOWN_RULE': [{'message': 'oops'}]},
        }
        serializer = self.serialize({'results': results})
        assert 'results' in serializer.errors
        assert 'UNKNOWN_RULE' in serializer.errors['results'][0]

    def test_extra_top_level_field_not_allowed(self):
        serializer = self.serialize(
            {'results': self.valid_results, 'unexpected': 'value'}
        )
        assert 'unexpected' in serializer.errors


VALID_YARA_DEFINITION = 'rule some_rule { condition: true }'


class TestScannerQueryRuleSerializer(TestCase):
    def _create_narc_rule(self):
        return ScannerQueryRule.objects.create(
            name='narc_rule', scanner=NARC, definition='test'
        )

    def test_create_valid(self):
        serializer = ScannerQueryRuleSerializer(
            data={
                'name': 'some_rule',
                'scanner': 'yara',
                'definition': VALID_YARA_DEFINITION,
            }
        )
        assert serializer.is_valid(), serializer.errors
        rule = serializer.save()
        assert rule.pk
        assert rule.name == 'some_rule'
        assert rule.scanner == YARA
        assert rule.state == NEW

    def test_yara_name_derived_from_definition(self):
        # name is not provided; it is inferred from the definition.
        serializer = ScannerQueryRuleSerializer(
            data={
                'scanner': 'yara',
                'definition': 'rule derived_name { condition: true }',
            }
        )
        assert serializer.is_valid(), serializer.errors
        rule = serializer.save()
        assert rule.name == 'derived_name'

    def test_yara_ignores_provided_name(self):
        # Any client-provided name is ignored for yara; the definition wins.
        serializer = ScannerQueryRuleSerializer(
            data={
                'name': 'ignored',
                'scanner': 'yara',
                'definition': 'rule derived_name { condition: true }',
            }
        )
        assert serializer.is_valid(), serializer.errors
        rule = serializer.save()
        assert rule.name == 'derived_name'

    def test_narc_requires_name(self):
        serializer = ScannerQueryRuleSerializer(
            data={'scanner': 'narc', 'definition': 'test'}
        )
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    def test_invalid_definition(self):
        serializer = ScannerQueryRuleSerializer(
            data={
                'scanner': 'yara',
                # Missing condition, so it does not compile.
                'definition': 'rule some_rule { }',
            }
        )
        assert not serializer.is_valid()
        assert 'definition' in serializer.errors

    def test_duplicate_name_and_scanner_rejected(self):
        ScannerQueryRule.objects.create(
            name='some_rule', scanner=YARA, definition=VALID_YARA_DEFINITION
        )
        # Derives name 'some_rule' from the definition -> collides with above.
        serializer = ScannerQueryRuleSerializer(
            data={'scanner': 'yara', 'definition': VALID_YARA_DEFINITION}
        )
        assert not serializer.is_valid()

    def test_scanner_choices_limited(self):
        serializer = ScannerQueryRuleSerializer(
            data={
                'name': 'some_rule',
                # webhook is not a valid query-rule scanner.
                'scanner': 'webhook',
                'definition': VALID_YARA_DEFINITION,
            }
        )
        assert not serializer.is_valid()
        assert 'scanner' in serializer.errors

    def test_read_only_fields_serialized(self):
        rule = ScannerQueryRule.objects.create(
            name='some_rule', scanner=YARA, definition=VALID_YARA_DEFINITION
        )
        data = ScannerQueryRuleSerializer(rule).data
        assert data['scanner'] == 'yara'
        assert data['state'] == 'new'
        assert 'scanner_display' not in data
        assert 'state_display' not in data
        assert data['results_count'] == 0
        assert data['completion_rate'] is None

    def test_cannot_update_when_not_new(self):
        rule = ScannerQueryRule.objects.create(
            name='some_rule', scanner=YARA, definition=VALID_YARA_DEFINITION
        )
        rule.update(state=RUNNING)
        serializer = ScannerQueryRuleSerializer(
            instance=rule, data={'description': 'updated'}, partial=True
        )
        assert not serializer.is_valid()

    def test_can_update_when_new(self):
        rule = ScannerQueryRule.objects.create(
            name='some_rule', scanner=YARA, definition=VALID_YARA_DEFINITION
        )
        serializer = ScannerQueryRuleSerializer(
            instance=rule, data={'description': 'updated'}, partial=True
        )
        assert serializer.is_valid(), serializer.errors
        rule = serializer.save()
        assert rule.description == 'updated'

    def test_name_and_scanner_read_only_after_create(self):
        rule = ScannerQueryRule.objects.create(
            name='some_rule', scanner=YARA, definition=VALID_YARA_DEFINITION
        )
        serializer = ScannerQueryRuleSerializer(
            instance=rule,
            data={'name': 'renamed', 'scanner': 'narc'},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        rule = serializer.save()
        # Both are ignored: they are read-only once the rule exists.
        assert rule.name == 'some_rule'
        assert rule.scanner == YARA

    def test_configuration_default_after_create(self):
        serializer = ScannerQueryRuleSerializer(
            data={'name': 'narc_rule', 'scanner': 'narc', 'definition': 'test'}
        )
        assert serializer.is_valid(), serializer.errors
        rule = serializer.save()
        assert rule.configuration == default_from_schema(NARC_RULE_CONFIGURATION_SCHEMA)

    def test_configuration_can_be_modified(self):
        rule = self._create_narc_rule()
        serializer = ScannerQueryRuleSerializer(
            instance=rule,
            data={'configuration': {'examine_slug': True}},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        rule = serializer.save()
        assert rule.configuration == {'examine_slug': True}

    def test_configuration_unknown_key_rejected(self):
        rule = self._create_narc_rule()
        serializer = ScannerQueryRuleSerializer(
            instance=rule,
            data={'configuration': {'not_a_real_option': True}},
            partial=True,
        )
        assert not serializer.is_valid()
        assert 'configuration' in serializer.errors

    def test_configuration_wrong_type_rejected(self):
        rule = self._create_narc_rule()
        serializer = ScannerQueryRuleSerializer(
            instance=rule,
            data={'configuration': {'examine_slug': 'not a boolean'}},
            partial=True,
        )
        assert not serializer.is_valid()
        assert 'configuration' in serializer.errors

    def test_configuration_rejected_for_yara(self):
        # yara rules have no configuration options.
        serializer = ScannerQueryRuleSerializer(
            data={
                'name': 'some_rule',
                'scanner': 'yara',
                'definition': VALID_YARA_DEFINITION,
                'configuration': {'examine_slug': True},
            }
        )
        assert not serializer.is_valid()
        assert 'configuration' in serializer.errors

    def test_run_on_specific_channels_uses_string_constants(self):
        serializer = ScannerQueryRuleSerializer(
            data={
                'name': 'some_rule',
                'scanner': 'yara',
                'definition': VALID_YARA_DEFINITION,
                'run_on_specific_channels': ['listed', 'enterprise'],
            }
        )
        assert serializer.is_valid(), serializer.errors
        rule = serializer.save()
        assert rule.run_on_specific_channels == [
            amo.CHANNEL_LISTED,
            amo.CHANNEL_ENTERPRISE,
        ]
        data = ScannerQueryRuleSerializer(rule).data
        assert data['run_on_specific_channels'] == ['listed', 'enterprise']

    def test_run_on_specific_channels_defaults_to_all_channels(self):
        serializer = ScannerQueryRuleSerializer(
            data={
                'name': 'some_rule',
                'scanner': 'yara',
                'definition': VALID_YARA_DEFINITION,
            }
        )
        assert serializer.is_valid(), serializer.errors
        rule = serializer.save()
        assert rule.run_on_specific_channels == list(amo.CHANNEL_CHOICES)
        data = ScannerQueryRuleSerializer(rule).data
        assert data['run_on_specific_channels'] == list(
            amo.CHANNEL_CHOICES_API.values()
        )

    def test_run_on_specific_channels_invalid_channel(self):
        serializer = ScannerQueryRuleSerializer(
            data={
                'name': 'some_rule',
                'scanner': 'yara',
                'definition': VALID_YARA_DEFINITION,
                'run_on_specific_channels': ['no'],
            }
        )
        assert not serializer.is_valid()
        assert 'run_on_specific_channels' in serializer.errors


class TestScannerQueryResultSerializer(TestCase):
    def test_serialize(self):
        ScannerQueryRule.objects.create(
            name='some_rule', scanner=YARA, definition=VALID_YARA_DEFINITION
        )
        addon = addon_factory(guid='@some-guid', average_daily_users=123)
        version = version_factory(addon=addon)
        result = ScannerQueryResult(scanner=YARA, version=version)
        result.add_yara_result(rule='some_rule', meta={'filename': 'foo.js'})
        result.save()

        data = ScannerQueryResultSerializer(result).data
        assert data.keys() == {
            'id',
            'was_blocked',
            'was_promoted',
            'version',
            'matches',
            'created',
        }
        assert data['id'] == result.pk
        assert data['was_blocked'] == result.was_blocked
        assert data['was_promoted'] == result.was_promoted
        assert data['version'].keys() == {
            'id',
            'version',
            'channel',
            'created',
            'addon',
        }
        assert data['version']['id'] == version.pk
        assert data['version']['channel'] == 'listed'
        assert data['version']['addon'] == {
            'id': addon.id,
            'guid': '@some-guid',
            'average_daily_users': 123,
        }
        assert 'some_rule' in data['matches']
