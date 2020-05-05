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
from olympia.constants.scanners import YARA, CUSTOMS, WAT, TRUE_POSITIVE
from olympia.scanners.models import ScannerResult
from olympia.scanners.serializers import ScannerResultSerializer
from django.test.utils import override_settings


class TestScannerResultView(TestCase):
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
        results = json['results']
        assert len(results) == expected_results
        return results

    def test_endpoint_requires_authentication(self):
        self.client.logout_api()
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_endpoint_requires_permissions(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_endpoint_can_be_disabled(self):
        self.create_switch('enable-scanner-results-api', active=False)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_get(self):
        self.create_switch('enable-scanner-results-api', active=True)
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
        VersionLog.objects.create(
            activity_log=ActivityLog.create(
                action=amo.LOG.APPROVE_VERSION,
                version=good_version_1,
                user=self.user,
            ),
            version=good_version_1,
        )
        # result labelled as "good" because auto-approve has been confirmed
        good_version_2 = version_factory(addon=addon_factory())
        good_result_2 = ScannerResult.objects.create(
            scanner=CUSTOMS, version=good_version_2
        )
        VersionLog.objects.create(
            activity_log=ActivityLog.create(
                action=amo.LOG.APPROVE_VERSION,
                version=good_version_2,
                user=task_user,
            ),
            version=good_version_2,
        )
        VersionLog.objects.create(
            activity_log=ActivityLog.create(
                action=amo.LOG.CONFIRM_AUTO_APPROVED,
                version=good_version_2,
                user=self.user,
            ),
            version=good_version_2,
        )
        # Simulate a reviewer who has confirmed auto-approval a second time. We
        # should not return duplicate results.
        VersionLog.objects.create(
            activity_log=ActivityLog.create(
                action=amo.LOG.CONFIRM_AUTO_APPROVED,
                version=good_version_2,
                user=self.user,
            ),
            version=good_version_2,
        )
        # result NOT labelled as "good" because action is not correct.
        version_3 = version_factory(addon=addon_factory())
        ScannerResult.objects.create(scanner=YARA, version=version_3)
        VersionLog.objects.create(
            activity_log=ActivityLog.create(
                action=amo.LOG.REJECT_VERSION,
                version=version_3,
                user=self.user,
            ),
            version=version_3,
        )
        # result NOT labelled as "good" because user is TASK_USER_ID
        version_4 = version_factory(addon=addon_factory())
        ScannerResult.objects.create(scanner=YARA, version=version_4)
        VersionLog.objects.create(
            activity_log=ActivityLog.create(
                action=amo.LOG.APPROVE_VERSION,
                version=version_4,
                user=task_user,
            ),
            version=version_4,
        )

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
        self.create_switch('enable-scanner-results-api', active=True)
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
        self.create_switch('enable-scanner-results-api', active=True)
        invalid_scanner = ""
        response = self.client.get(
            '{}?scanner={}'.format(self.url, invalid_scanner)
        )
        assert response.status_code == 400

    def test_get_by_scanner_with_unknown_scanner(self):
        self.create_switch('enable-scanner-results-api', active=True)
        invalid_scanner = "yaraaaa"
        response = self.client.get(
            '{}?scanner={}'.format(self.url, invalid_scanner)
        )
        assert response.status_code == 400

    def test_get_by_label(self):
        self.create_switch('enable-scanner-results-api', active=True)
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
        self.create_switch('enable-scanner-results-api', active=True)
        invalid_label = ""
        response = self.client.get(
            '{}?label={}'.format(self.url, invalid_label)
        )
        assert response.status_code == 400

    def test_get_by_label_with_unknown_label(self):
        self.create_switch('enable-scanner-results-api', active=True)
        invalid_label = "gooda"
        response = self.client.get(
            '{}?label={}'.format(self.url, invalid_label)
        )
        assert response.status_code == 400

    def test_get_by_label_and_scanner(self):
        self.create_switch('enable-scanner-results-api', active=True)
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
