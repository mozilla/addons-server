import pytest

from django.test.utils import override_settings
from django.urls.exceptions import NoReverseMatch

from olympia import amo
from olympia.activity.models import ActivityLog, VersionLog
from olympia.amo.tests import (
    APITestClient,
    TestCase,
    addon_factory,
    reverse_ns,
    user_factory,
    version_factory,
)
from olympia.api.tests.utils import APIKeyAuthTestMixin
from olympia.constants.scanners import (
    CUSTOMS,
    LABEL_BAD,
    MAD,
    TRUE_POSITIVE,
    WAT,
    YARA,
)
from olympia.blocklist.models import Block
from olympia.blocklist.utils import block_activity_log_save
from olympia.scanners.models import ScannerResult
from olympia.scanners.serializers import ScannerResultSerializer


@pytest.mark.internal_routes_allowed
class TestScannerResultViewInternal(TestCase):
    client_class = APITestClient

    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:ScannersResultsView')
        self.client.login_api(self.user)
        self.url = reverse_ns('scanner-results', api_version='v5')

    def assert_json_results(self, response, expected_results):
        json = response.json()
        assert 'results' in json
        assert 'count' in json
        assert json['count'] == expected_results
        return json['results']

    def test_endpoint_requires_authentication(self):
        self.client.logout_api()
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_endpoint_requires_permissions(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get(self):
        task_user = user_factory()
        # result labelled as "bad" because its state is TRUE_POSITIVE
        bad_version = version_factory(addon=addon_factory())
        bad_result = ScannerResult.objects.create(
            scanner=YARA, version=bad_version, state=TRUE_POSITIVE
        )
        # result without a version and state is UNKNOWN
        ScannerResult.objects.create(scanner=YARA)
        # true positive, but without a version
        ScannerResult.objects.create(scanner=YARA, state=TRUE_POSITIVE)
        # result labelled as "good" because it has been approved
        good_version_1 = version_factory(addon=addon_factory())
        good_result_1 = ScannerResult.objects.create(
            scanner=WAT, version=good_version_1
        )
        ActivityLog.create(
            amo.LOG.APPROVE_VERSION, good_version_1, user=self.user
        )
        # result labelled as "good" because auto-approve has been confirmed
        good_version_2 = version_factory(addon=addon_factory())
        good_result_2 = ScannerResult.objects.create(
            scanner=CUSTOMS, version=good_version_2
        )
        ActivityLog.create(
            amo.LOG.APPROVE_VERSION, good_version_2, user=task_user
        )
        ActivityLog.create(
            amo.LOG.CONFIRM_AUTO_APPROVED, good_version_2, user=self.user
        )
        # Simulate a reviewer who has confirmed auto-approval a second time. We
        # should not return duplicate results.
        ActivityLog.create(
            amo.LOG.CONFIRM_AUTO_APPROVED, good_version_2, user=self.user
        )
        # result NOT labelled as "good" because action is not correct.
        version_3 = version_factory(addon=addon_factory())
        ScannerResult.objects.create(scanner=YARA, version=version_3)
        ActivityLog.create(amo.LOG.REJECT_VERSION, version_3, user=self.user)
        # result NOT labelled as "good" because user is TASK_USER_ID
        version_4 = version_factory(addon=addon_factory())
        ScannerResult.objects.create(scanner=YARA, version=version_4)
        ActivityLog.create(amo.LOG.APPROVE_VERSION, version_4, user=task_user)

        with override_settings(TASK_USER_ID=task_user.pk):
            response = self.client.get(self.url)

        assert response.status_code == 200
        results = self.assert_json_results(response, expected_results=3)
        # Force a `label` value so that the serialized (expected) data is
        # accurate. This is needed because `label` is an annotated field
        # created in the QuerySet.
        good_result_2.label = 'good'
        assert (
            results[0] == ScannerResultSerializer(instance=good_result_2).data
        )
        # Force a `label` value so that the serialized (expected) data is
        # accurate. This is needed because `label` is an annotated field
        # created in the QuerySet.
        good_result_1.label = 'good'
        assert (
            results[1] == ScannerResultSerializer(instance=good_result_1).data
        )
        # Force a `label` value so that the serialized (expected) data is
        # accurate. This is needed because `label` is an annotated field
        # created in the QuerySet.
        bad_result.label = 'bad'
        assert results[2] == ScannerResultSerializer(instance=bad_result).data

    def test_get_by_scanner(self):
        # result labelled as "bad" because its state is TRUE_POSITIVE
        bad_version = version_factory(addon=addon_factory())
        ScannerResult.objects.create(
            scanner=YARA, version=bad_version, state=TRUE_POSITIVE
        )
        ScannerResult.objects.create(
            scanner=CUSTOMS, version=bad_version, state=TRUE_POSITIVE
        )

        response = self.client.get(self.url)
        self.assert_json_results(response, expected_results=2)

        response = self.client.get('{}?scanner=yara'.format(self.url))
        results = self.assert_json_results(response, expected_results=1)
        assert results[0].get('scanner') == 'yara'

        response = self.client.get('{}?scanner=customs'.format(self.url))
        results = self.assert_json_results(response, expected_results=1)
        assert results[0].get('scanner') == 'customs'

    def test_get_by_scanner_with_empty_value(self):
        invalid_scanner = ""
        response = self.client.get(
            '{}?scanner={}'.format(self.url, invalid_scanner)
        )
        assert response.status_code == 400

    def test_get_by_scanner_with_unknown_scanner(self):
        invalid_scanner = "yaraaaa"
        response = self.client.get(
            '{}?scanner={}'.format(self.url, invalid_scanner)
        )
        assert response.status_code == 400

    def test_get_by_label(self):
        # result labelled as "bad" because its state is TRUE_POSITIVE
        bad_version = version_factory(addon=addon_factory())
        ScannerResult.objects.create(
            scanner=YARA, version=bad_version, state=TRUE_POSITIVE
        )
        # result labelled as "good" because it has been approved
        good_version = version_factory(addon=addon_factory())
        ScannerResult.objects.create(scanner=WAT, version=good_version)
        VersionLog.objects.create(
            activity_log=ActivityLog.create(
                action=amo.LOG.APPROVE_VERSION,
                version=good_version,
                user=self.user,
            ),
            version=good_version,
        )

        response = self.client.get(self.url)
        self.assert_json_results(response, expected_results=2)

        response = self.client.get('{}?label=good'.format(self.url))
        results = self.assert_json_results(response, expected_results=1)
        assert results[0].get('label') == 'good'

        response = self.client.get('{}?label=bad'.format(self.url))
        results = self.assert_json_results(response, expected_results=1)
        assert results[0].get('label') == 'bad'

    def test_get_by_label_with_empty_value(self):
        invalid_label = ""
        response = self.client.get(
            '{}?label={}'.format(self.url, invalid_label)
        )
        assert response.status_code == 400

    def test_get_by_label_with_unknown_label(self):
        invalid_label = "gooda"
        response = self.client.get(
            '{}?label={}'.format(self.url, invalid_label)
        )
        assert response.status_code == 400

    def test_get_by_label_and_scanner(self):
        # result labelled as "bad" because its state is TRUE_POSITIVE
        bad_version = version_factory(addon=addon_factory())
        ScannerResult.objects.create(
            scanner=YARA, version=bad_version, state=TRUE_POSITIVE
        )
        # result labelled as "good" because it has been approved
        good_version = version_factory(addon=addon_factory())
        ScannerResult.objects.create(scanner=WAT, version=good_version)
        VersionLog.objects.create(
            activity_log=ActivityLog.create(
                action=amo.LOG.APPROVE_VERSION,
                version=good_version,
                user=self.user,
            ),
            version=good_version,
        )

        response = self.client.get(self.url)
        self.assert_json_results(response, expected_results=2)

        response = self.client.get(
            '{}'.format('{}?scanner=yara&label=good'.format(self.url))
        )
        self.assert_json_results(response, expected_results=0)
        response = self.client.get(
            '{}'.format('{}?scanner=yara&label=bad'.format(self.url))
        )
        self.assert_json_results(response, expected_results=1)

        response = self.client.get(
            '{}'.format('{}?scanner=wat&label=bad'.format(self.url))
        )
        self.assert_json_results(response, expected_results=0)
        response = self.client.get(
            '{}'.format('{}?scanner=wat&label=good'.format(self.url))
        )
        self.assert_json_results(response, expected_results=1)

    def test_get_results_with_blocked_versions(self):
        # result labelled as "bad" because its state is TRUE_POSITIVE
        bad_version = version_factory(addon=addon_factory())
        ScannerResult.objects.create(
            scanner=YARA, version=bad_version, state=TRUE_POSITIVE
        )
        # result labelled as "bad" because the add-on is blocked.
        blocked_addon_1 = addon_factory()
        blocked_version_1 = version_factory(addon=blocked_addon_1)
        ScannerResult.objects.create(scanner=YARA, version=blocked_version_1)
        block_1 = Block.objects.create(
            guid=blocked_addon_1.guid, updated_by=self.user
        )
        block_activity_log_save(block_1, change=False)
        # result labelled as "bad" because the add-on is blocked and the block
        # has been edited.
        blocked_addon_2 = addon_factory()
        blocked_version_2 = version_factory(addon=blocked_addon_2)
        ScannerResult.objects.create(scanner=YARA, version=blocked_version_2)
        block_2 = Block.objects.create(
            guid=blocked_addon_2.guid, updated_by=self.user
        )
        block_activity_log_save(block_2, change=True)
        # result labelled as "bad" because the add-on is blocked and the block
        # has been added *and* edited. It should only return one result.
        blocked_addon_3 = addon_factory()
        blocked_version_3 = version_factory(addon=blocked_addon_3)
        ScannerResult.objects.create(scanner=YARA, version=blocked_version_3)
        block_3 = Block.objects.create(
            guid=blocked_addon_3.guid, updated_by=self.user
        )
        block_activity_log_save(block_3, change=False)
        block_activity_log_save(block_3, change=True)
        # result labelled as "bad" because its state is TRUE_POSITIVE and the
        # add-on is blocked. It should only return one result.
        blocked_addon_4 = addon_factory()
        blocked_version_4 = version_factory(addon=blocked_addon_4)
        ScannerResult.objects.create(
            scanner=YARA, version=blocked_version_4, state=TRUE_POSITIVE
        )
        block_4 = Block.objects.create(
            guid=blocked_addon_4.guid, updated_by=self.user
        )
        block_activity_log_save(block_4, change=False)

        response = self.client.get(self.url)
        self.assert_json_results(response, expected_results=5)

    def test_get_results_with_good_blocked_versions(self):
        # Result labelled as "good" because auto-approve has been confirmed.
        version_1 = version_factory(addon=addon_factory())
        result_1 = ScannerResult.objects.create(
            scanner=CUSTOMS, version=version_1
        )
        ActivityLog.create(amo.LOG.APPROVE_VERSION, version_1, user=self.user)
        # Oh noes! The version has been blocked.
        block_1 = Block.objects.create(
            guid=version_1.addon.guid, updated_by=self.user
        )
        block_activity_log_save(block_1, change=False)

        response = self.client.get(self.url)
        results = self.assert_json_results(response, expected_results=1)
        assert results[0]['id'] == result_1.id
        assert results[0]['label'] == LABEL_BAD

    def test_get_unique_bad_results(self):
        version_1 = version_factory(addon=addon_factory(), version='1.0')
        ScannerResult.objects.create(scanner=MAD, version=version_1)
        ActivityLog.create(
            amo.LOG.BLOCKLIST_BLOCK_ADDED, version_1, user=self.user
        )
        ActivityLog.create(
            amo.LOG.BLOCKLIST_BLOCK_EDITED, version_1, user=self.user
        )
        version_2 = version_factory(addon=addon_factory(), version='2.0')
        ScannerResult.objects.create(scanner=MAD, version=version_2)
        ActivityLog.create(
            amo.LOG.BLOCKLIST_BLOCK_ADDED, version_2, user=self.user
        )
        ActivityLog.create(
            amo.LOG.BLOCKLIST_BLOCK_EDITED, version_2, user=self.user
        )

        response = self.client.get('{}?label=bad'.format(self.url))
        results = self.assert_json_results(response, expected_results=2)
        assert results[0]['id'] != results[1]['id']

    def test_get_unique_good_results(self):
        version_1 = version_factory(addon=addon_factory(), version='1.0')
        ScannerResult.objects.create(scanner=MAD, version=version_1)
        ActivityLog.create(amo.LOG.APPROVE_VERSION, version_1, user=self.user)
        ActivityLog.create(
            amo.LOG.CONFIRM_AUTO_APPROVED, version_1, user=self.user
        )
        ActivityLog.create(
            amo.LOG.CONFIRM_AUTO_APPROVED, version_1, user=self.user
        )
        version_2 = version_factory(addon=addon_factory(), version='2.0')
        ScannerResult.objects.create(scanner=MAD, version=version_2)
        ActivityLog.create(amo.LOG.APPROVE_VERSION, version_2, user=self.user)
        ActivityLog.create(
            amo.LOG.CONFIRM_AUTO_APPROVED, version_2, user=self.user
        )
        ActivityLog.create(
            amo.LOG.CONFIRM_AUTO_APPROVED, version_2, user=self.user
        )

        response = self.client.get('{}?label=good'.format(self.url))
        results = self.assert_json_results(response, expected_results=2)
        assert results[0]['id'] != results[1]['id']


@pytest.mark.internal_routes_allowed
class TestScannerResultViewInternalWithJWT(APIKeyAuthTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.create_api_user()
        self.grant_permission(self.user, 'Admin:ScannersResultsView')
        self.url = reverse_ns('scanner-results', api_version='v5')

    def test_accepts_jwt_auth(self):
        response = self.get(self.url)

        assert response.status_code == 200


class TestScannerResultView(TestCase):
    def test_route_does_not_exist(self):
        with self.assertRaises(NoReverseMatch):
            assert not reverse_ns('scanner-results', api_version='v5')
