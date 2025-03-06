from copy import deepcopy

from waffle.testutils import override_switch

from olympia import amo
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
        return_value = annotate_validation_results(results=results, parsed_data=data)
        assert return_value == results
        assert results['errors'] == 0
        assert len(results['messages']) == 0

    def test_allowed_origins(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.com')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://bar.com']}
        return_value = annotate_validation_results(results=results, parsed_data=data)
        assert return_value == results
        assert results['errors'] == 0
        assert len(results['messages']) == 0

    def test_allowed_origins_multiple(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.com')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://bar.com', 'https://example.com']}
        return_value = annotate_validation_results(results=results, parsed_data=data)
        assert return_value == results
        assert results['errors'] == 0
        assert len(results['messages']) == 0

    def test_some_invalid_origins(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.com')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://bar.com', 'https://foo.com']}
        return_value = annotate_validation_results(results=results, parsed_data=data)
        assert return_value == results
        assert results['errors'] == 1
        assert results['messages'][0] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://foo.com is not permitted.',
            'description': [],
            'extra': True,  # This didn't come from the linter.
            'compatibility_type': None,
        }

    def test_invalid_origins_multiple_matches_same_origin(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.com')
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.*')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://bar.com', 'https://foo.com']}
        return_value = annotate_validation_results(results=results, parsed_data=data)
        assert return_value == results
        assert results['errors'] == 1
        assert results['messages'][0] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://foo.com is not permitted.',
            'description': [],
            'extra': True,  # This didn't come from the linter.
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
        return_value = annotate_validation_results(results=results, parsed_data=data)
        assert return_value == results
        assert results['errors'] == 2
        assert results['messages'][0] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://foo.fr is not permitted.',
            'description': [],
            'extra': True,  # This didn't come from the linter.
            'compatibility_type': None,
        }
        assert results['messages'][1] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://foo.com is not permitted.',
            'description': [],
            'extra': True,  # This didn't come from the linter.
            'compatibility_type': None,
        }

    def test_invalid_origins_multiple_matches_multiple_patterns(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='bar.com')
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.*')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {'install_origins': ['https://bar.com', 'https://foo.com']}
        return_value = annotate_validation_results(results=results, parsed_data=data)
        assert return_value == results
        assert results['errors'] == 2
        assert results['messages'][0] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://foo.com is not permitted.',
            'description': [],
            'extra': True,  # This didn't come from the linter.
            'compatibility_type': None,
        }
        assert results['messages'][1] == {
            'tier': 1,
            'type': 'error',
            'id': ['validation', 'messages', ''],
            'message': 'The install origin https://bar.com is not permitted.',
            'description': [],
            'extra': True,  # This didn't come from the linter.
            'compatibility_type': None,
        }

    def test_empty_parsed_data(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.com')
        results = deepcopy(VALIDATOR_SKELETON_RESULTS)
        data = {}
        return_value = annotate_validation_results(results=results, parsed_data=data)
        assert return_value == results
        assert results['errors'] == 0
        assert len(results['messages']) == 0


class TestAddManifestVersionMessages(TestCase):
    def test_add_manifest_version_message_not_listed(self):
        results = deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT)
        results['messages'] = []
        results['metadata']['manifestVersion'] = 3
        data = {}
        annotate_validation_results(results=results, parsed_data=data)
        # mv3 submission switch is off so we should have added the message even
        # for an unlisted submission.
        assert len(results['messages']) == 1
        # It should be inserted at the top.
        assert (
            'https://blog.mozilla.org/addons/2021/05/27/manifest-v3-update/'
            in (results['messages'][0]['message'])
        )

    def test_add_manifest_version_message_not_mv3(self):
        results = deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT)
        results['messages'] = []
        results['metadata']['manifestVersion'] = 2
        data = {}
        annotate_validation_results(results=results, parsed_data=data)
        assert results['messages'] == []

    def test_add_manifest_version_message_switch_enabled(self):
        results = deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT)
        results['messages'] = []
        results['metadata']['manifestVersion'] = 3
        data = {}
        with override_switch('enable-mv3-submissions', active=True):
            annotate_validation_results(results=results, parsed_data=data)
            assert results['messages'] == []

    def test_add_manifest_version_message(self):
        results = deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT)
        assert len(results['messages']) == 1

        # Add the error message when the manifest_version is 3 and the switch to
        # enable mv3 submissions is off (the default).
        # The manifest_version error isn't in VALIDATOR_SKELETON_EXCEPTION_WEBEXT.
        results['metadata']['manifestVersion'] = 3
        data = {}
        annotate_validation_results(results=results, parsed_data=data)
        assert len(results['messages']) == 2  # we added it
        # It should be inserted at the top.
        assert (
            'https://blog.mozilla.org/addons/2021/05/27/manifest-v3-update/'
            in (results['messages'][0]['message'])
        )

    def test_add_manifest_version_message_replace(self):
        results = deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT)
        # When the linter error is already there, replace it
        results['messages'] = [
            {
                'message': '"/manifest_version" should be &lt;= 2',
                'description': ['Your JSON file could not be parsed.'],
                'instancePath': '/manifest_version',
                'type': 'error',
                'tier': 1,
            }
        ]
        results['metadata']['manifestVersion'] = 3
        data = {}
        annotate_validation_results(results=results, parsed_data=data)
        assert len(results['messages']) == 1  # we replaced it and not added it.
        assert (
            'https://blog.mozilla.org/addons/2021/05/27/manifest-v3-update/'
            in (results['messages'][0]['message'])
        )
