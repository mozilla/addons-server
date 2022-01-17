import json
import time

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from unittest import mock

from django.test import RequestFactory
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.encoding import force_str

from waffle.testutils import override_switch

from olympia.accounts import utils
from olympia.accounts.utils import process_fxa_event
from olympia.amo.tests import TestCase, user_factory


FXA_CONFIG = {
    'default': {
        'client_id': 'foo',
        'client_secret': 'bar',
    },
}


@override_settings(FXA_CONFIG=FXA_CONFIG)
@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_without_requiring_two_factor_auth():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        action='signin',
        force_two_factor=False,
    )

    url = urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path
    )
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'action': ['signin'],
        'client_id': ['foo'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_CONFIG=FXA_CONFIG)
@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        action='signin',
        force_two_factor=True,
    )

    url = urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path
    )
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'acr_values': ['AAL2'],
        'action': ['signin'],
        'client_id': ['foo'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


@override_settings(FXA_CONFIG=FXA_CONFIG)
@override_settings(FXA_OAUTH_HOST='https://accounts.firefox.com/oauth')
def test_fxa_login_url_requiring_two_factor_auth_passing_token():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}

    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        action='signin',
        force_two_factor=True,
        id_token='YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo=',
    )

    url = urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path
    )
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'acr_values': ['AAL2'],
        'action': ['signin'],
        'client_id': ['foo'],
        'id_token_hint': ['YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo='],
        'prompt': ['none'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


def test_unicode_next_path():
    path = '/en-US/føø/bãr'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'fake-state'}
    url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=utils.path_with_query(request),
        action='signin',
    )
    state = parse_qs(urlparse(url).query)['state'][0]
    next_path = urlsafe_b64decode(state.split(':')[1] + '===')
    assert next_path.decode('utf-8') == path


@override_settings(FXA_CONFIG=FXA_CONFIG)
def test_redirect_for_login():
    request = RequestFactory().get('/somewhere')
    request.session = {'fxa_state': 'fake-state'}
    response = utils.redirect_for_login(request)
    assert response['location'] == utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path='/somewhere',
        action='signin',
    )


@override_settings(DEBUG=True, USE_FAKE_FXA_AUTH=True)
def test_fxa_login_url_when_faking_fxa_auth():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}
    raw_url = utils.fxa_login_url(
        config=FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path,
        action='signin',
    )
    url = urlparse(raw_url)
    assert url.scheme == ''
    assert url.netloc == ''
    assert url.path == reverse('fake-fxa-authorization')
    query = parse_qs(url.query)
    next_path = urlsafe_b64encode(path.encode('utf-8')).rstrip(b'=')
    assert query == {
        'action': ['signin'],
        'client_id': ['foo'],
        'scope': ['profile openid'],
        'state': [f'myfxastate:{force_str(next_path)}'],
        'access_type': ['offline'],
    }


class TestProcessSqsQueue(TestCase):
    @mock.patch('boto3._get_default_session')
    @mock.patch('olympia.accounts.utils.process_fxa_event')
    @mock.patch('boto3.client')
    def test_process_sqs_queue(self, client, process_fxa_event, get_session):
        messages = [
            {'Body': 'foo', 'ReceiptHandle': '$$$'},
            {'Body': 'bar'},
            None,
            {'Body': 'thisonetoo'},
        ]
        sqs = mock.MagicMock(
            **{'receive_message.side_effect': [{'Messages': messages}]}
        )
        session_mock = mock.MagicMock(
            **{'get_available_regions.side_effect': ['nowh-ere']}
        )
        get_session.return_value = session_mock
        delete_mock = mock.MagicMock()
        sqs.delete_message = delete_mock
        client.return_value = sqs

        with self.assertRaises(StopIteration):
            utils.process_sqs_queue(queue_url='https://sqs.nowh-ere.aws.com/123456789/')

        client.assert_called()
        client.assert_called_with('sqs', region_name='nowh-ere')
        process_fxa_event.assert_called()
        # The 'None' in messages would cause an exception, but it should be
        # handled, and the remaining message(s) still processed.
        process_fxa_event.assert_has_calls(
            [mock.call('foo'), mock.call('bar'), mock.call('thisonetoo')]
        )
        delete_mock.assert_called_once()  # Receipt handle is present in foo.
        delete_mock.assert_called_with(
            QueueUrl='https://sqs.nowh-ere.aws.com/123456789/', ReceiptHandle='$$$'
        )

    @mock.patch('olympia.accounts.utils.primary_email_change_event.delay')
    @mock.patch('olympia.accounts.utils.delete_user_event.delay')
    def test_malformed_body_doesnt_throw(self, email_mock, delete_mock):
        process_fxa_event('')
        process_fxa_event(json.dumps({'Message': ''}))
        process_fxa_event(json.dumps({'Message': 'ddfdfd'}))
        # No timestamps
        process_fxa_event(
            json.dumps(
                {
                    'Message': json.dumps(
                        {
                            'email': 'foo@baa',
                            'event': 'primaryEmailChanged',
                            'uid': '999',
                        }
                    )
                }
            )
        )
        process_fxa_event(
            json.dumps({'Message': json.dumps({'event': 'delete', 'uid': '999'})})
        )
        # Not a supported event type
        process_fxa_event(
            json.dumps(
                {
                    'Message': json.dumps(
                        {
                            'email': 'foo@baa',
                            'event': 'not-an-event',
                            'uid': '999',
                            'ts': totimestamp(datetime.now()),
                        }
                    )
                }
            )
        )
        delete_mock.assert_not_called()
        email_mock.assert_not_called()


def totimestamp(datetime_obj):
    return time.mktime(datetime_obj.timetuple())


class TestProcessFxAEventEmail(TestCase):
    fxa_id = 'ABCDEF012345689'

    def setUp(self):
        self.email_changed_date = self.days_ago(42)
        self.body = json.dumps(
            {
                'Message': json.dumps(
                    {
                        'email': 'new-email@example.com',
                        'event': 'primaryEmailChanged',
                        'uid': self.fxa_id,
                        'ts': totimestamp(self.email_changed_date),
                    }
                )
            }
        )

    def test_success_integration(self):
        user = user_factory(email='old-email@example.com', fxa_id=self.fxa_id)
        process_fxa_event(self.body)
        user.reload()
        assert user.email == 'new-email@example.com'
        assert user.email_changed == self.email_changed_date

    def test_success_integration_previously_changed_once(self):
        user = user_factory(
            email='old-email@example.com',
            fxa_id=self.fxa_id,
            email_changed=datetime(2017, 10, 11),
        )
        process_fxa_event(self.body)
        user.reload()
        assert user.email == 'new-email@example.com'
        assert user.email_changed == self.email_changed_date

    @mock.patch('olympia.accounts.utils.primary_email_change_event.delay')
    def test_success(self, primary_email_change_event):
        process_fxa_event(self.body)
        primary_email_change_event.assert_called()
        primary_email_change_event.assert_called_with(
            self.fxa_id, totimestamp(self.email_changed_date), 'new-email@example.com'
        )


class TestProcessFxAEventDelete(TestCase):
    fxa_id = 'ABCDEF012345689'

    def setUp(self):
        self.email_changed_date = self.days_ago(42)
        self.body = json.dumps(
            {
                'Message': json.dumps(
                    {
                        'event': 'delete',
                        'uid': self.fxa_id,
                        'ts': totimestamp(self.email_changed_date),
                    }
                )
            }
        )

    @override_switch('fxa-account-delete', active=True)
    def test_success_integration(self):
        user = user_factory(fxa_id=self.fxa_id)
        process_fxa_event(self.body)
        user.reload()
        assert user.email is not None
        assert user.deleted
        assert user.fxa_id is not None

    @mock.patch('olympia.accounts.utils.delete_user_event.delay')
    def test_success(self, delete_user_event_mock):
        process_fxa_event(self.body)
        delete_user_event_mock.assert_called()
        delete_user_event_mock.assert_called_with(
            self.fxa_id, totimestamp(self.email_changed_date)
        )


class TestProcessFxAEventResetTestCase(TestCase):
    fxa_id = 'ABCDEF012345689'
    event = 'reset'

    def setUp(self):
        self.event_date = self.days_ago(42)
        self.body = json.dumps(
            {
                'Message': json.dumps(
                    {
                        'event': self.event,
                        'uid': self.fxa_id,
                        'ts': totimestamp(self.event_date),
                    }
                )
            }
        )

    def test_success_integration(self):
        user = user_factory(fxa_id=self.fxa_id)
        process_fxa_event(self.body)
        user.reload()
        assert user.auth_id is None

    @mock.patch('olympia.accounts.utils.clear_sessions_event.delay')
    def test_success(self, clear_sessions_event_mock):
        process_fxa_event(self.body)
        clear_sessions_event_mock.assert_called()
        clear_sessions_event_mock.assert_called_with(
            self.fxa_id, totimestamp(self.event_date), self.event
        )


class TestProcessFxAEventPasswordChangeTestCase(TestProcessFxAEventResetTestCase):
    event = 'passwordChange'
