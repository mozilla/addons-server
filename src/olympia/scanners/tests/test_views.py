from olympia.amo.tests import (
    TestCase,
    addon_factory,
    reverse_ns,
    version_factory,
)
from olympia.api.models import APIKey
from olympia.api.tests.utils import APIKeyAuthTestMixin
from olympia.constants.scanners import (
    WEBHOOK,
    WEBHOOK_DURING_VALIDATION,
    WEBHOOK_PUSH,
    YARA,
)
from olympia.scanners.models import (
    ScannerResult,
    ScannerRule,
    ScannerWebhook,
    ScannerWebhookEvent,
)


class TestPatchScannerResult(APIKeyAuthTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.webhook = ScannerWebhook.objects.create(
            name='test-webhook',
            url='https://example.com/webhook',
            api_key='secret',
        )
        webhook_event = ScannerWebhookEvent.objects.create(
            webhook=self.webhook,
            event=WEBHOOK_DURING_VALIDATION,
        )
        self.api_key = APIKey.get_jwt_key(user=self.webhook.service_account)

        self.version = version_factory(addon=addon_factory())
        self.scanner_result = ScannerResult.objects.create(
            scanner=WEBHOOK,
            version=self.version,
            webhook_event=webhook_event,
        )

        self.url = reverse_ns(
            'scanner-result-patch',
            api_version='v5',
            kwargs={'pk': self.scanner_result.pk},
        )

    def test_success(self):
        assert not self.scanner_result.results

        results = {'version': '1.2.3', 'matchedRules': []}
        response = self.patch(self.url, data={'results': results})

        assert response.status_code == 204
        self.scanner_result.refresh_from_db()
        assert self.scanner_result.results == results

    def test_success_with_null_results(self):
        self.scanner_result.update(results=None)

        results = {'version': '1.2.3', 'matchedRules': []}
        response = self.patch(self.url, data={'results': results})

        assert response.status_code == 204
        self.scanner_result.refresh_from_db()
        assert self.scanner_result.results == results

    def test_success_when_scanner_webhooks_switch_is_enabled(self):
        self.create_switch('enable-scanner-webhooks', active=True)
        self.test_success()

    def test_cannot_patch_twice(self):
        # First patch should succeed.
        results = {'version': '1.2.3', 'matchedRules': []}
        response = self.patch(self.url, data={'results': results})
        assert response.status_code == 204

        # Second patch should fail with 409 Conflict.
        results = {'version': '1.2.4', 'matchedRules': ['some-rule']}
        response = self.patch(self.url, data={'results': results})
        assert response.status_code == 409
        assert response.json() == {'detail': 'Scanner result has already been updated'}

    def test_wrong_service_account(self):
        # Create a different service account
        other_webhook = ScannerWebhook.objects.create(
            name='other-webhook',
            url='https://example.com/other',
            api_key='secret2',
        )
        self.api_key = APIKey.get_jwt_key(user=other_webhook.service_account)

        results = {'version': '1.2.3', 'matchedRules': []}
        response = self.patch(self.url, data={'results': results})

        assert response.status_code == 404

    def test_scanner_result_not_found(self):
        invalid_url = reverse_ns(
            'scanner-result-patch', api_version='v5', kwargs={'pk': 999999}
        )

        results = {'version': '1.2.3', 'matchedRules': []}
        response = self.patch(invalid_url, data={'results': results})

        assert response.status_code == 404

    def test_scanner_result_not_webhook_scanner(self):
        yara_result = ScannerResult.objects.create(scanner=YARA, version=self.version)
        yara_url = reverse_ns(
            'scanner-result-patch',
            api_version='v5',
            kwargs={'pk': yara_result.pk},
        )

        results = {'version': '1.2.3', 'matchedRules': []}
        response = self.patch(yara_url, data={'results': results})

        assert response.status_code == 404

    def test_scanner_result_webhook_event_is_null(self):
        result_without_event = ScannerResult.objects.create(
            scanner=WEBHOOK,
            version=self.version,
            webhook_event=None,
        )
        url = reverse_ns(
            'scanner-result-patch',
            api_version='v5',
            kwargs={'pk': result_without_event.pk},
        )

        results = {'version': '1.2.3', 'matchedRules': []}
        response = self.patch(url, data={'results': {'results': results}})

        assert response.status_code == 404

    def test_invalid_payload_missing_results(self):
        response = self.patch(self.url, data={'other': 'value'})

        assert response.status_code == 400
        assert response.json() == {'results': ['This field is required.']}

    def test_invalid_payload_extra_keys(self):
        results = {'version': '1.2.3', 'matchedRules': []}
        response = self.patch(self.url, data={'results': results, 'extra': 'key'})

        assert response.status_code == 400
        assert response.json() == {'extra': ['Unexpected field.']}

    def test_invalid_payload_empty(self):
        response = self.patch(self.url, data={})

        assert response.status_code == 400

    def test_success_extracts_matched_rules(self):
        rule = ScannerRule.objects.create(
            name='some-rule',
            scanner=WEBHOOK,
            is_active=True,
        )

        results = {'version': '1.2.3', 'matchedRules': [rule.name]}
        response = self.patch(self.url, data={'results': results})

        assert response.status_code == 204
        self.scanner_result.refresh_from_db()
        assert self.scanner_result.has_matches is True
        assert list(self.scanner_result.matched_rules.all()) == [rule]

    def test_invalid_group(self):
        self.webhook.service_account.groupuser_set.all().delete()

        results = {'version': '1.2.3', 'matchedRules': []}
        response = self.patch(self.url, data={'results': results})

        assert response.status_code == 403


class TestPushScannerResult(APIKeyAuthTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.webhook = ScannerWebhook.objects.create(
            name='test-webhook',
            url='https://example.com/webhook',
            api_key='secret',
        )
        ScannerWebhookEvent.objects.create(webhook=self.webhook, event=WEBHOOK_PUSH)
        self.api_key = APIKey.get_jwt_key(user=self.webhook.service_account)
        self.grant_permission(
            self.webhook.service_account,
            'Scanners:PushResults',
            'some access group',
        )

        self.version = version_factory(addon=addon_factory())
        self.url = reverse_ns('scanner-result-push', api_version='v5')
        self.results = {'version': '1.0.0', 'matchedRules': []}

    def _push_scanner_result(self, data=None):
        if data is None:
            data = {'version_id': self.version.pk, 'results': self.results}
        return self.post(self.url, data=data, format='json')

    def test_success(self):
        response = self._push_scanner_result()

        assert response.status_code == 201
        scanner_result = ScannerResult.objects.get()
        assert response.json() == {'id': scanner_result.pk}
        assert scanner_result.scanner == WEBHOOK
        assert scanner_result.version == self.version
        assert scanner_result.results == self.results
        assert scanner_result.webhook_event.event == WEBHOOK_PUSH
        assert scanner_result.webhook_event.webhook == self.webhook

    def test_multiple_results_allowed(self):
        self._push_scanner_result()
        response = self._push_scanner_result()

        assert response.status_code == 201
        assert (
            ScannerResult.objects.filter(
                version=self.version,
                scanner=WEBHOOK,
            ).count()
            == 2
        )

    def test_no_push_event(self):
        ScannerWebhookEvent.objects.filter(
            webhook=self.webhook, event=WEBHOOK_PUSH
        ).delete()
        response = self._push_scanner_result()

        assert response.status_code == 403

    def test_inactive_webhook(self):
        self.webhook.update(is_active=False)
        response = self._push_scanner_result()

        assert response.status_code == 403

    def test_no_permission(self):
        self.webhook.service_account.groupuser_set.all().delete()
        response = self._push_scanner_result()

        assert response.status_code == 403

    def test_version_not_found(self):
        response = self._push_scanner_result(
            data={'version_id': 999999, 'results': self.results}
        )

        assert response.status_code == 400
        assert response.json() == {'version_id': ['Version not found.']}

    def test_invalid_payload(self):
        response = self._push_scanner_result(data={'version_id': self.version.pk})

        assert response.status_code == 400
        assert response.json() == {'results': ['This field is required.']}
