from unittest import mock

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    reverse_ns,
    version_factory,
)
from olympia.api.models import APIKey
from olympia.api.tests.utils import APIKeyAuthTestMixin
from olympia.constants.scanners import (
    ABORTING,
    COMPLETED,
    NEW,
    RUNNING,
    SCHEDULED,
    WEBHOOK,
    WEBHOOK_DURING_VALIDATION,
    WEBHOOK_PUSH,
    YARA,
)
from olympia.scanners.models import (
    ScannerQueryResult,
    ScannerQueryRule,
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

    @mock.patch('olympia.scanners.views.log')
    def test_success(self, log_mock):
        assert not self.scanner_result.results

        results = {'version': '1.2.3', 'matchedRules': []}
        response = self.patch(self.url, data={'results': results})

        assert response.status_code == 204
        self.scanner_result.refresh_from_db()
        assert self.scanner_result.results == results
        assert log_mock.info.call_count == 1
        assert (
            log_mock.info.call_args[0][0]
            == 'Patched existing scanner result %s for version %s'
        )
        assert log_mock.info.call_args[0][1] == self.scanner_result.pk
        assert log_mock.info.call_args[0][2] == self.scanner_result.version.pk

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
        self.event = ScannerWebhookEvent.objects.create(
            webhook=self.webhook,
            event=WEBHOOK_PUSH,
        )
        self.api_key = APIKey.get_jwt_key(user=self.webhook.service_account)
        self.grant_permission(
            self.webhook.service_account,
            'Scanners:PushResults',
            'some access group',
        )

        self.version = version_factory(addon=addon_factory())
        self.url = reverse_ns('scanner-result-push', api_version='v5')
        self.results = {'version': '1.0.0', 'matchedRules': []}
        for name in ('rule-a', 'rule-b', 'rule-c'):
            ScannerRule.objects.create(name=name, scanner=WEBHOOK, is_active=True)

    def _push_scanner_result(self, data=None):
        if data is None:
            data = {'version_id': self.version.pk, 'results': self.results}
        return self.post(self.url, data=data, format='json')

    @mock.patch('olympia.scanners.views.log')
    def test_success(self, log_mock):
        response = self._push_scanner_result()

        assert response.status_code == 201
        scanner_result = ScannerResult.objects.get()
        assert response.json() == {'id': scanner_result.pk}
        assert scanner_result.scanner == WEBHOOK
        assert scanner_result.version == self.version
        assert scanner_result.results == self.results
        assert scanner_result.webhook_event.event == WEBHOOK_PUSH
        assert scanner_result.webhook_event.webhook == self.webhook
        assert log_mock.info.call_count == 1
        assert (
            log_mock.info.call_args[0][0]
            == 'Pushed new scanner result %s for version %s'
        )
        assert log_mock.info.call_args[0][1] == scanner_result.pk
        assert log_mock.info.call_args[0][2] == self.version.pk

    def test_multiple_results_allowed_when_no_matched_rules(self):
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

    def test_multiple_results_allowed_with_disjoint_rules(self):
        first = self._push_scanner_result(
            data={
                'version_id': self.version.pk,
                'results': {'version': '1.0.0', 'matchedRules': ['rule-a']},
            }
        )
        assert first.status_code == 201

        second = self._push_scanner_result(
            data={
                'version_id': self.version.pk,
                'results': {'version': '1.0.0', 'matchedRules': ['rule-b']},
            }
        )
        assert second.status_code == 201
        assert (
            ScannerResult.objects.filter(
                version=self.version,
                scanner=WEBHOOK,
            ).count()
            == 2
        )

    def test_rejects_duplicate_rule(self):
        first = self._push_scanner_result(
            data={
                'version_id': self.version.pk,
                'results': {'version': '1.0.0', 'matchedRules': ['rule-a']},
            }
        )
        assert first.status_code == 201

        second = self._push_scanner_result(
            data={
                'version_id': self.version.pk,
                'results': {'version': '1.0.0', 'matchedRules': ['rule-a']},
            }
        )
        assert second.status_code == 409
        assert second.json() == {
            'detail': 'Scanner result already pushed for one of the rules'
        }
        assert (
            ScannerResult.objects.filter(
                version=self.version,
                scanner=WEBHOOK,
            ).count()
            == 1
        )

    def test_rejects_partial_rule_overlap(self):
        first = self._push_scanner_result(
            data={
                'version_id': self.version.pk,
                'results': {
                    'version': '1.0.0',
                    'matchedRules': ['rule-a', 'rule-b'],
                },
            }
        )
        assert first.status_code == 201

        second = self._push_scanner_result(
            data={
                'version_id': self.version.pk,
                'results': {
                    'version': '1.0.0',
                    'matchedRules': ['rule-b', 'rule-c'],
                },
            }
        )
        assert second.status_code == 409
        assert second.json() == {
            'detail': 'Scanner result already pushed for one of the rules'
        }

    def test_same_rule_allowed_for_different_version(self):
        first = self._push_scanner_result(
            data={
                'version_id': self.version.pk,
                'results': {'version': '1.0.0', 'matchedRules': ['rule-a']},
            }
        )
        assert first.status_code == 201

        other_version = version_factory(addon=self.version.addon)
        second = self._push_scanner_result(
            data={
                'version_id': other_version.pk,
                'results': {'version': '1.0.1', 'matchedRules': ['rule-a']},
            }
        )
        assert second.status_code == 201

    def test_same_rule_allowed_for_different_webhook(self):
        first = self._push_scanner_result(
            data={
                'version_id': self.version.pk,
                'results': {'version': '1.0.0', 'matchedRules': ['rule-a']},
            }
        )
        assert first.status_code == 201

        other_webhook = ScannerWebhook.objects.create(
            name='other-webhook',
            url='https://example.com/other',
            api_key='secret2',
        )
        ScannerWebhookEvent.objects.create(
            webhook=other_webhook,
            event=WEBHOOK_PUSH,
        )
        self.api_key = APIKey.get_jwt_key(user=other_webhook.service_account)
        self.grant_permission(
            other_webhook.service_account,
            'Scanners:PushResults',
            'some access group',
        )

        second = self._push_scanner_result(
            data={
                'version_id': self.version.pk,
                'results': {'version': '1.0.0', 'matchedRules': ['rule-a']},
            }
        )
        assert second.status_code == 201

    def test_no_push_event(self):
        self.event.delete()
        response = self._push_scanner_result()

        assert response.status_code == 403

    def test_inactive_push_event(self):
        self.event.update(is_active=False)
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


VALID_YARA_DEFINITION = 'rule some_rule { condition: true }'


class TestScannerQueryRuleViewSet(APIKeyAuthTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.create_api_user()
        self.grant_permission(
            self.user, 'Admin:ScannersQueryEdit', 'Scanner query editors'
        )
        self.grant_permission(
            self.user, 'Admin:ScannersQueryView', 'Scanner query viewers'
        )
        self.list_url = reverse_ns('scanner-query-rule-list', api_version='v5')

    def _detail_url(self, rule, action=None):
        name = 'scanner-query-rule-detail'
        if action:
            name = f'scanner-query-rule-{action}'
        return reverse_ns(name, api_version='v5', kwargs={'pk': rule.pk})

    def _create_rule(self, **kwargs):
        defaults = {
            'name': 'some_rule',
            'scanner': YARA,
            'definition': VALID_YARA_DEFINITION,
        }
        defaults.update(kwargs)
        return ScannerQueryRule.objects.create(**defaults)

    def test_auth_required(self):
        response = self.client.get(self.list_url)
        assert response.status_code == 401

    def test_permission_required(self):
        self.user.groupuser_set.all().delete()
        response = self.get(self.list_url)
        assert response.status_code == 403

    def test_write_operations_require_edit_permission(self):
        rule = self._create_rule()
        self.user.groupuser_set.all().delete()
        # Read-only permission, no write access
        self.grant_permission(
            self.user, 'Admin:ScannersQueryView', 'Scanner query viewers'
        )
        detail_url = self._detail_url(rule)
        payload = {'scanner': 'yara', 'definition': VALID_YARA_DEFINITION}

        assert self.post(self.list_url, data=payload, format='json').status_code == 403
        assert (
            self.patch(detail_url, data={'description': 'x'}, format='json').status_code
            == 403
        )
        assert self.put(detail_url, data=payload, format='json').status_code == 403
        assert self.delete(detail_url).status_code == 403
        assert self.post(self._detail_url(rule, action='run')).status_code == 403
        assert self.post(self._detail_url(rule, action='abort')).status_code == 403

        # Reads still work, and nothing was created, modified or deleted:
        assert self.get(detail_url).status_code == 200
        assert ScannerQueryRule.objects.count() == 1
        rule.refresh_from_db()
        assert rule.description == ''
        assert rule.state == NEW

    def test_list(self):
        rule = self._create_rule()
        response = self.get(self.list_url)
        assert response.status_code == 200
        data = response.json()
        assert data['count'] == 1
        assert data['results'][0]['id'] == rule.pk

    def test_create(self):
        response = self.post(
            self.list_url,
            data={
                'name': 'some_rule',
                'pretty_name': 'Some rule',
                'scanner': 'yara',
                'definition': VALID_YARA_DEFINITION,
            },
            format='json',
        )
        assert response.status_code == 201, response.content
        rule = ScannerQueryRule.objects.get()
        assert rule.name == 'some_rule'
        assert rule.scanner == YARA
        assert rule.state == NEW
        data = response.json()
        assert data['id'] == rule.pk
        assert data['scanner'] == 'yara'
        assert data['state'] == 'new'
        # The definition should be echoed back (creator has view access).
        assert data['definition'] == VALID_YARA_DEFINITION

    def test_create_invalid_definition(self):
        response = self.post(
            self.list_url,
            data={
                'scanner': 'yara',
                # Missing condition, so it does not compile.
                'definition': 'rule some_rule { }',
            },
            format='json',
        )
        assert response.status_code == 400
        assert 'definition' in response.json()
        assert not ScannerQueryRule.objects.exists()

    def test_patch_while_new(self):
        rule = self._create_rule()
        response = self.patch(
            self._detail_url(rule),
            data={'description': 'updated'},
            format='json',
        )
        assert response.status_code == 200, response.content
        rule.refresh_from_db()
        assert rule.description == 'updated'

    def test_cannot_patch_once_not_new(self):
        rule = self._create_rule()
        rule.update(state=RUNNING)
        response = self.patch(
            self._detail_url(rule),
            data={'description': 'updated'},
            format='json',
        )
        assert response.status_code == 400
        rule.refresh_from_db()
        assert rule.description == ''

    def test_name_and_scanner_read_only_after_create(self):
        rule = self._create_rule()
        response = self.patch(
            self._detail_url(rule),
            data={'name': 'renamed', 'scanner': 'narc'},
            format='json',
        )
        assert response.status_code == 200, response.content
        rule.refresh_from_db()
        # Both were ignored: read-only once the rule exists.
        assert rule.name == 'some_rule'
        assert rule.scanner == YARA

    def test_delete(self):
        rule = self._create_rule()
        response = self.delete(self._detail_url(rule))
        assert response.status_code == 204
        assert not ScannerQueryRule.objects.exists()

    @mock.patch('olympia.scanners.views.run_scanner_query_rule')
    def test_run(self, run_task_mock):
        rule = self._create_rule()
        response = self.post(self._detail_url(rule, action='run'))
        assert response.status_code == 202, response.content
        rule.refresh_from_db()
        assert rule.state == SCHEDULED
        run_task_mock.delay.assert_called_once_with(rule.pk)

    @mock.patch('olympia.scanners.views.run_scanner_query_rule')
    def test_run_invalid_state(self, run_task_mock):
        rule = self._create_rule()
        rule.update(state=COMPLETED)
        response = self.post(self._detail_url(rule, action='run'))
        assert response.status_code == 409
        run_task_mock.delay.assert_not_called()

    def test_abort(self):
        rule = self._create_rule()
        rule.update(state=RUNNING)
        response = self.post(self._detail_url(rule, action='abort'))
        assert response.status_code == 200
        rule.refresh_from_db()
        assert rule.state == ABORTING

    def test_abort_invalid_state(self):
        rule = self._create_rule()
        rule.update(state=COMPLETED)
        response = self.post(self._detail_url(rule, action='abort'))
        assert response.status_code == 409
        rule.refresh_from_db()
        assert rule.state == COMPLETED


class TestScannerQueryResultViewSet(APIKeyAuthTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.create_api_user()
        self.grant_permission(
            self.user, 'Admin:ScannersQueryView', 'Scanner query viewers'
        )
        self.rule = ScannerQueryRule.objects.create(
            name='some_rule', scanner=YARA, definition=VALID_YARA_DEFINITION
        )
        version = version_factory(addon=addon_factory())
        self.result = ScannerQueryResult(scanner=YARA, version=version)
        self.result.add_yara_result(rule='some_rule', meta={'filename': 'foo.js'})
        self.result.save()
        assert self.result.matched_rule == self.rule
        self.list_url = self._list_url(self.rule)

    def _list_url(self, rule):
        return reverse_ns(
            'scanner-query-rule-result-list',
            api_version='v5',
            kwargs={'query_rule_pk': rule.pk},
        )

    def test_auth_required(self):
        response = self.client.get(self.list_url)
        assert response.status_code == 401

    def test_permission_required(self):
        self.user.groupuser_set.all().delete()
        response = self.get(self.list_url)
        assert response.status_code == 403

    def test_list(self):
        response = self.get(self.list_url)
        assert response.status_code == 200
        data = response.json()
        assert data['count'] == 1
        assert data['results'][0]['id'] == self.result.pk
        assert 'some_rule' in data['results'][0]['matches']

    def test_unknown_rule_returns_404(self):
        url = reverse_ns(
            'scanner-query-rule-result-list',
            api_version='v5',
            kwargs={'query_rule_pk': 999999},
        )
        response = self.get(url)
        assert response.status_code == 404

    def test_scoped_to_parent_rule(self):
        other_rule = ScannerQueryRule.objects.create(
            name='other_rule',
            scanner=YARA,
            definition='rule other_rule { condition: true }',
        )
        response = self.get(self._list_url(other_rule))
        assert response.status_code == 200
        assert response.json()['count'] == 0

    def _create_result(
        self,
        *,
        adu=0,
        channel=amo.CHANNEL_LISTED,
        was_blocked=None,
        was_promoted=None,
        is_signed=False,
        addon_status=amo.STATUS_APPROVED,
        file_status=amo.STATUS_APPROVED,
        disabled_by_user=False,
    ):
        version = version_factory(
            addon=addon_factory(
                average_daily_users=adu,
                status=addon_status,
                disabled_by_user=disabled_by_user,
            ),
            channel=channel,
            file_kw={'is_signed': is_signed, 'status': file_status},
        )
        result = ScannerQueryResult(
            scanner=YARA,
            version=version,
            was_blocked=was_blocked,
            was_promoted=was_promoted,
        )
        result.add_yara_result(rule='some_rule')
        result.save()
        assert result.matched_rule == self.rule
        return result

    def _ids(self, response):
        return [r['id'] for r in response.json()['results']]

    def test_filter_was_blocked(self):
        blocked = self._create_result(was_blocked=True)
        self._create_result(was_blocked=False)

        response = self.get(self.list_url, data={'was_blocked': 'true'})
        assert response.status_code == 200
        assert self._ids(response) == [blocked.pk]

    def test_filter_was_promoted(self):
        promoted = self._create_result(was_promoted=True)
        self._create_result(was_promoted=False)

        response = self.get(self.list_url, data={'was_promoted': 'true'})
        assert response.status_code == 200
        assert self._ids(response) == [promoted.pk]

    def test_filter_was_signed(self):
        signed = self._create_result(is_signed=True)
        self._create_result(is_signed=False)

        response = self.get(self.list_url, data={'was_signed': 'true'})
        assert response.status_code == 200
        # self.result (setUp) is unsigned, so only the signed one matches.
        assert self._ids(response) == [signed.pk]

    def test_filter_addon_disabled_by_user(self):
        invisible = self._create_result(disabled_by_user=True)
        self._create_result(disabled_by_user=False)

        response = self.get(self.list_url, data={'addon_disabled_by_user': 'true'})
        assert response.status_code == 200
        assert self._ids(response) == [invisible.pk]

    def test_filter_addon_status(self):
        disabled = self._create_result(addon_status=amo.STATUS_DISABLED)
        self._create_result(addon_status=amo.STATUS_APPROVED)

        response = self.get(self.list_url, data={'addon_status': 'disabled'})
        assert response.status_code == 200
        assert self._ids(response) == [disabled.pk]

    def test_filter_file_status(self):
        disabled = self._create_result(file_status=amo.STATUS_DISABLED)
        self._create_result(file_status=amo.STATUS_APPROVED)

        response = self.get(self.list_url, data={'file_status': 'disabled'})
        assert response.status_code == 200
        assert self._ids(response) == [disabled.pk]

    def test_filter_channel(self):
        unlisted = self._create_result(channel=amo.CHANNEL_UNLISTED)
        self._create_result(channel=amo.CHANNEL_LISTED)

        response = self.get(self.list_url, data={'channel': 'unlisted'})
        assert response.status_code == 200
        assert self._ids(response) == [unlisted.pk]

    def test_invalid_filter_value_returns_400(self):
        response = self.get(self.list_url, data={'was_blocked': 'notabool'})
        assert response.status_code == 400

        response = self.get(self.list_url, data={'channel': 'notanint'})
        assert response.status_code == 400

    def test_order_by_adu(self):
        low = self._create_result(adu=1)
        high = self._create_result(adu=1000)

        ids = self._ids(self.get(self.list_url, data={'sort': 'addon_adu'}))
        assert ids.index(low.pk) < ids.index(high.pk)

        ids = self._ids(self.get(self.list_url, data={'sort': '-addon_adu'}))
        assert ids.index(high.pk) < ids.index(low.pk)

    def test_order_by_version_created(self):
        older = self._create_result()
        newer = self._create_result()
        older.version.update(created=self.days_ago(10))
        newer.version.update(created=self.days_ago(1))

        ids = self._ids(self.get(self.list_url, data={'sort': 'version_created'}))
        assert ids.index(older.pk) < ids.index(newer.pk)

        ids = self._ids(self.get(self.list_url, data={'sort': '-version_created'}))
        assert ids.index(newer.pk) < ids.index(older.pk)

    def test_default_ordering_is_newest_first(self):
        newer = self._create_result()
        # self.result (setUp) is older, self.result.pk < newer.pk.
        ids = self._ids(self.get(self.list_url))
        assert ids.index(newer.pk) < ids.index(self.result.pk)
