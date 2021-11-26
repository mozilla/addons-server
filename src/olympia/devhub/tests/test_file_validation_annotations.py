from copy import deepcopy

from waffle.testutils import override_switch

from olympia.amo.tests import TestCase
from olympia.constants.base import VALIDATOR_SKELETON_RESULTS
from olympia.devhub.file_validation_annotations import annotate_validation_results
from olympia.versions.models import DeniedInstallOrigin


@override_switch('record-install-origins', active=True)
class TestDeniedOrigins(TestCase):
    @override_switch('record-install-origins', active=False)
    def test_waffle_switch_off(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.com')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://foo.com']}
        return_value = annotate_validation_results(results, data)
        assert return_value == results
        assert results['errors'] == 0
        assert len(results['messages']) == 0

    def test_allowed_origins(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.com')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://bar.com']}
        return_value = annotate_validation_results(results, data)
        assert return_value == results
        assert results['errors'] == 0
        assert len(results['messages']) == 0

    def test_allowed_origins_multiple(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.com')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://bar.com', 'https://example.com']}
        return_value = annotate_validation_results(results, data)
        assert return_value == results
        assert results['errors'] == 0
        assert len(results['messages']) == 0

    def test_some_invalid_origins(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.com')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://bar.com', 'https://foo.com']}
        return_value = annotate_validation_results(results, data)
        assert return_value == results
        assert results['errors'] == 1
        assert results['messages'][0] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://foo.com is not permitted.',
            'description': [],
            'compatibility_type': None,
        }

    def test_invalid_origins_multiple_matches_same_origin(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.com')
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.*')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://bar.com', 'https://foo.com']}
        return_value = annotate_validation_results(results, data)
        assert return_value == results
        assert results['errors'] == 1
        assert results['messages'][0] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://foo.com is not permitted.',
            'description': [],
            'compatibility_type': None,
        }

    def test_invalid_origins_multiple_matches_same_pattern(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='bar.com')
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.*')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {
            'install_origins': [
                'https://example.com',
                'https://foo.fr',
                'https://foo.com',
            ]
        }
        return_value = annotate_validation_results(results, data)
        assert return_value == results
        assert results['errors'] == 2
        assert results['messages'][0] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://foo.fr is not permitted.',
            'description': [],
            'compatibility_type': None,
        }
        assert results['messages'][1] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://foo.com is not permitted.',
            'description': [],
            'compatibility_type': None,
        }

    def test_invalid_origins_multiple_matches_multiple_patterns(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='bar.com')
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.*')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://bar.com', 'https://foo.com']}
        return_value = annotate_validation_results(results, data)
        assert return_value == results
        assert results['errors'] == 2
        assert results['messages'][0] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://foo.com is not permitted.',
            'description': [],
            'compatibility_type': None,
        }
        assert results['messages'][1] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://bar.com is not permitted.',
            'description': [],
            'compatibility_type': None,
        }
