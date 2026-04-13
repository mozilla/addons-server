import json
from unittest import mock

from django.conf import settings
from django.test import override_settings

import requests
import responses

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.reviewers.models import NeedsHumanReview, ZendeskTicket
from olympia.reviewers.tasks import (
    add_zendesk_comment_for_activity_log,
    close_zendesk_ticket,
    create_zendesk_ticket,
)
from olympia.reviewers.zendesk import ZendeskClient, build_comment_body, build_ticket_body
from olympia.users.models import UserProfile


ZENDESK_SETTINGS = {
    'ZENDESK_API_EMAIL': 'amo@mozilla.com',
    'ZENDESK_API_TOKEN': 'test-token',
    'ZENDESK_SUBDOMAIN': 'mozilla-test',
    'ZENDESK_AMO_BRAND_ID': 98765,
}

TICKET_RESPONSE = {
    'ticket': {
        'id': 42,
        'subject': 'Add-on Review: Some Addon 1.0',
        'status': 'new',
        'external_id': '99',
    }
}

ME_RESPONSE = {'user': {'id': 999}}


class TestZendeskClient(TestCase):
    @responses.activate
    @override_settings(**ZENDESK_SETTINGS)
    def test_create_ticket(self):
        responses.add(
            responses.POST,
            'https://mozilla-test.zendesk.com/api/v2/tickets.json',
            json=TICKET_RESPONSE,
            status=201,
        )
        client = ZendeskClient()
        ticket_id, requester_id = client.create_ticket(
            subject='Add-on Review: Some Addon 1.0',
            body='some body',
            external_id='99',
        )
        assert ticket_id == '42'
        assert requester_id is None  # not present in TICKET_RESPONSE
        payload = json.loads(responses.calls[0].request.body)
        assert payload['ticket']['subject'] == 'Add-on Review: Some Addon 1.0'
        assert payload['ticket']['external_id'] == '99'

    @responses.activate
    @override_settings(**ZENDESK_SETTINGS)
    def test_close_ticket_sets_assignee_when_unset(self):
        responses.add(
            responses.GET,
            'https://mozilla-test.zendesk.com/api/v2/tickets/42.json',
            json={'ticket': {'id': 42, 'assignee_id': None}},
            status=200,
        )
        responses.add(
            responses.GET,
            'https://mozilla-test.zendesk.com/api/v2/users/me.json',
            json=ME_RESPONSE,
            status=200,
        )
        responses.add(
            responses.PUT,
            'https://mozilla-test.zendesk.com/api/v2/tickets/42.json',
            json={'ticket': {'id': 42, 'status': 'solved'}},
            status=200,
        )
        client = ZendeskClient()
        client.close_ticket('42')
        payload = json.loads(responses.calls[2].request.body)
        assert payload['ticket']['status'] == 'solved'
        assert payload['ticket']['assignee_id'] == 999

    @responses.activate
    @override_settings(**ZENDESK_SETTINGS)
    def test_close_ticket_keeps_existing_assignee(self):
        responses.add(
            responses.GET,
            'https://mozilla-test.zendesk.com/api/v2/tickets/42.json',
            json={'ticket': {'id': 42, 'assignee_id': 777}},
            status=200,
        )
        responses.add(
            responses.PUT,
            'https://mozilla-test.zendesk.com/api/v2/tickets/42.json',
            json={'ticket': {'id': 42, 'status': 'solved'}},
            status=200,
        )
        client = ZendeskClient()
        client.close_ticket('42')
        payload = json.loads(responses.calls[1].request.body)
        assert payload['ticket']['status'] == 'solved'
        assert 'assignee_id' not in payload['ticket']

    @responses.activate
    @override_settings(**ZENDESK_SETTINGS)
    def test_create_ticket_raises_on_error(self):
        responses.add(
            responses.POST,
            'https://mozilla-test.zendesk.com/api/v2/tickets.json',
            status=422,
            json={'error': 'Unprocessable Entity'},
        )
        client = ZendeskClient()
        with self.assertRaises(requests.HTTPError):
            client.create_ticket(subject='x', body='y', external_id='1')

    @responses.activate
    @override_settings(**ZENDESK_SETTINGS)
    def test_set_user_fxa_id(self):
        responses.add(
            responses.PUT,
            'https://mozilla-test.zendesk.com/api/v2/users/555.json',
            json={'user': {'id': 555}},
            status=200,
        )
        client = ZendeskClient()
        client.set_user_fxa_id(555, 'abc123fxa')
        payload = json.loads(responses.calls[0].request.body)
        assert payload['user']['user_fields']['user_id'] == 'abc123fxa'

    @responses.activate
    @override_settings(**ZENDESK_SETTINGS)
    def test_add_private_comment(self):
        responses.add(
            responses.PUT,
            'https://mozilla-test.zendesk.com/api/v2/tickets/42.json',
            json={'ticket': {'id': 42}},
            status=200,
        )
        client = ZendeskClient()
        client.add_comment('42', 'hello', public=False)
        payload = json.loads(responses.calls[0].request.body)
        assert payload['ticket']['comment']['body'] == 'hello'
        assert payload['ticket']['comment']['public'] is False


class TestCreateZendeskTicketTask(TestCase):
    def setUp(self):
        self.addon = addon_factory(name='My Addon')
        self.version = self.addon.current_version

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_creates_ticket_and_saves_model(self, MockClient):
        MockClient.return_value.create_ticket.return_value = ('100', None)
        create_zendesk_ticket(self.version.pk)
        assert ZendeskTicket.objects.filter(version=self.version).exists()
        zt = ZendeskTicket.objects.get(version=self.version)
        assert zt.ticket_id == '100'

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_idempotent_does_not_create_duplicate(self, MockClient):
        MockClient.return_value.create_ticket.return_value = ('100', None)
        ZendeskTicket.objects.create(version=self.version, ticket_id='100')
        create_zendesk_ticket(self.version.pk)
        MockClient.return_value.create_ticket.assert_not_called()
        assert ZendeskTicket.objects.filter(version=self.version).count() == 1

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_skips_if_version_deleted(self, MockClient):
        pk = self.version.pk
        self.version.delete()
        create_zendesk_ticket(pk)
        MockClient.return_value.create_ticket.assert_not_called()

    @override_settings(ZENDESK_API_TOKEN=None)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_skips_when_not_configured(self, MockClient):
        create_zendesk_ticket(self.version.pk)
        MockClient.assert_not_called()

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_handles_api_error_gracefully(self, MockClient):
        MockClient.return_value.create_ticket.side_effect = requests.HTTPError(
            'bad request'
        )
        create_zendesk_ticket(self.version.pk)
        assert not ZendeskTicket.objects.filter(version=self.version).exists()

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_sets_fxa_id_on_requester(self, MockClient):
        MockClient.return_value.create_ticket.return_value = ('100', 555)
        author = UserProfile.objects.create(
            username='author', email='author@example.com', fxa_id='abc123'
        )
        self.addon.addonuser_set.create(user=author, listed=True)
        create_zendesk_ticket(self.version.pk)
        MockClient.return_value.set_user_fxa_id.assert_called_once_with(555, 'abc123')

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_skips_fxa_id_when_no_requester_id(self, MockClient):
        MockClient.return_value.create_ticket.return_value = ('100', None)
        create_zendesk_ticket(self.version.pk)
        MockClient.return_value.set_user_fxa_id.assert_not_called()


class TestCloseZendeskTicketTask(TestCase):
    def setUp(self):
        self.addon = addon_factory(name='My Addon')
        self.version = self.addon.current_version
        self.zt = ZendeskTicket.objects.create(version=self.version, ticket_id='99')

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_closes_ticket(self, MockClient):
        close_zendesk_ticket(self.version.pk)
        MockClient.return_value.close_ticket.assert_called_once_with('99')

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_skips_when_no_ticket(self, MockClient):
        self.zt.delete()
        close_zendesk_ticket(self.version.pk)
        MockClient.return_value.close_ticket.assert_not_called()

    @override_settings(ZENDESK_API_TOKEN=None)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_skips_when_not_configured(self, MockClient):
        close_zendesk_ticket(self.version.pk)
        MockClient.assert_not_called()

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_handles_api_error_gracefully(self, MockClient):
        MockClient.return_value.close_ticket.side_effect = requests.HTTPError(
            'server error'
        )
        # Should not raise — errors are caught and logged.
        close_zendesk_ticket(self.version.pk)


class TestNeedsHumanReviewSignal(TestCase):
    def setUp(self):
        # NeedsHumanReview.save() logs an activity that needs a task user.
        UserProfile.objects.get_or_create(pk=settings.TASK_USER_ID)

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.tasks.create_zendesk_ticket')
    def test_signal_fires_create_task_on_new_active_nhr(self, mock_task):
        addon = addon_factory()
        version = addon.current_version
        NeedsHumanReview.objects.create(
            version=version, reason=NeedsHumanReview.REASONS.SCANNER_ACTION
        )
        mock_task.delay.assert_called_once_with(version.pk)

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.tasks.create_zendesk_ticket')
    def test_signal_does_not_fire_on_update(self, mock_task):
        addon = addon_factory()
        version = addon.current_version
        nhr = NeedsHumanReview.objects.create(
            version=version, reason=NeedsHumanReview.REASONS.SCANNER_ACTION
        )
        mock_task.delay.reset_mock()
        # Updating (not creating) should not trigger the task again.
        nhr.is_active = False
        nhr.save(update_fields=['is_active'])
        mock_task.delay.assert_not_called()


class TestAddZendeskCommentTask(TestCase):
    def setUp(self):
        self.addon = addon_factory(name='My Addon')
        self.version = self.addon.current_version
        self.zt = ZendeskTicket.objects.create(version=self.version, ticket_id='77')
        self.user = UserProfile.objects.get_or_create(
            username='reviewer', defaults={'email': 'reviewer@mozilla.com'}
        )[0]

    def _create_log(self, action):
        return ActivityLog.objects.create(
            action, self.addon, self.version, user=self.user, details={'comments': 'hi'}
        )

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_adds_comment_to_ticket(self, MockClient):
        log_entry = self._create_log(amo.LOG.REVIEWER_REPLY_VERSION)
        add_zendesk_comment_for_activity_log(log_entry.pk)
        MockClient.return_value.add_comment.assert_called_once_with(
            '77', mock.ANY, public=False
        )

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_skips_when_no_ticket(self, MockClient):
        self.zt.delete()
        log_entry = self._create_log(amo.LOG.REVIEWER_REPLY_VERSION)
        add_zendesk_comment_for_activity_log(log_entry.pk)
        MockClient.return_value.add_comment.assert_not_called()

    @override_settings(ZENDESK_API_TOKEN=None)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_skips_when_not_configured(self, MockClient):
        log_entry = self._create_log(amo.LOG.REVIEWER_REPLY_VERSION)
        add_zendesk_comment_for_activity_log(log_entry.pk)
        MockClient.assert_not_called()

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_handles_api_error_gracefully(self, MockClient):
        MockClient.return_value.add_comment.side_effect = requests.HTTPError('error')
        log_entry = self._create_log(amo.LOG.REVIEWER_REPLY_VERSION)
        # Should not raise.
        add_zendesk_comment_for_activity_log(log_entry.pk)

    @override_settings(**ZENDESK_SETTINGS)
    @mock.patch('olympia.reviewers.zendesk.ZendeskClient')
    def test_skips_missing_activity_log(self, MockClient):
        add_zendesk_comment_for_activity_log(99999999)
        MockClient.return_value.add_comment.assert_not_called()


class TestBuildCommentBody(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        self.version = self.addon.current_version
        self.user = UserProfile.objects.get_or_create(
            username='reviewer2',
            defaults={'email': 'reviewer2@mozilla.com', 'display_name': 'Baku'},
        )[0]

    def _create_log(self, action, comments=None):
        details = {'comments': comments} if comments else {}
        return ActivityLog.objects.create(
            action, self.addon, self.version, user=self.user, details=details
        )

    def test_includes_action_label_and_author(self):
        log_entry = self._create_log(amo.LOG.REVIEWER_REPLY_VERSION)
        body = build_comment_body(log_entry)
        assert 'Reviewer Reply' in body
        assert self.user.name in body

    def test_includes_comment_text(self):
        log_entry = self._create_log(amo.LOG.REVIEWER_REPLY_VERSION, comments='LGTM!')
        body = build_comment_body(log_entry)
        assert 'LGTM!' in body

    def test_no_comment_text(self):
        log_entry = self._create_log(amo.LOG.REVIEWER_REPLY_VERSION)
        body = build_comment_body(log_entry)
        # No double newline when there's no comment.
        assert '\n\n' not in body
