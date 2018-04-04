# -*- coding: utf-8 -*-
import json
import time
import urlparse

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.test.utils import override_settings

import mock

from olympia.accounts import utils
from olympia.accounts.utils import process_fxa_event
from olympia.amo.tests import TestCase, user_factory
from olympia.users.models import UserProfile


FXA_CONFIG = {
    'default': {
        'client_id': 'foo',
        'client_secret': 'bar',
        'oauth_host': 'https://accounts.firefox.com/oauth',
        'redirect_url': 'https://testserver/fxa',
        'scope': 'profile',
    },
}


@override_settings(FXA_CONFIG=FXA_CONFIG)
def test_fxa_config_anonymous():
    request = RequestFactory().get('/en-US/firefox/addons')
    request.session = {'fxa_state': 'thestate!'}
    request.user = AnonymousUser()
    assert utils.fxa_config(request) == {
        'clientId': 'foo',
        'state': 'thestate!',
        'oauthHost': 'https://accounts.firefox.com/oauth',
        'redirectUrl': 'https://testserver/fxa',
        'scope': 'profile',
    }


@override_settings(FXA_CONFIG=FXA_CONFIG)
def test_fxa_config_logged_in():
    request = RequestFactory().get('/en-US/firefox/addons')
    request.session = {'fxa_state': 'thestate!'}
    request.user = UserProfile(email='me@mozilla.org')
    assert utils.fxa_config(request) == {
        'clientId': 'foo',
        'state': 'thestate!',
        'email': 'me@mozilla.org',
        'oauthHost': 'https://accounts.firefox.com/oauth',
        'redirectUrl': 'https://testserver/fxa',
        'scope': 'profile',
    }


@override_settings(FXA_CONFIG=FXA_CONFIG)
def test_default_fxa_login_url_with_state():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}
    raw_url = utils.default_fxa_login_url(request)
    url = urlparse.urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path)
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = urlparse.parse_qs(url.query)
    next_path = urlsafe_b64encode(path).rstrip('=')
    assert query == {
        'action': ['signin'],
        'client_id': ['foo'],
        'redirect_url': ['https://testserver/fxa'],
        'scope': ['profile'],
        'state': ['myfxastate:{next_path}'.format(next_path=next_path)],
    }


@override_settings(FXA_CONFIG=FXA_CONFIG)
def test_default_fxa_register_url_with_state():
    path = '/en-US/addons/abp/?source=ddg'
    request = RequestFactory().get(path)
    request.session = {'fxa_state': 'myfxastate'}
    raw_url = utils.default_fxa_register_url(request)
    url = urlparse.urlparse(raw_url)
    base = '{scheme}://{netloc}{path}'.format(
        scheme=url.scheme, netloc=url.netloc, path=url.path)
    assert base == 'https://accounts.firefox.com/oauth/authorization'
    query = urlparse.parse_qs(url.query)
    next_path = urlsafe_b64encode(path).rstrip('=')
    assert query == {
        'action': ['signup'],
        'client_id': ['foo'],
        'redirect_url': ['https://testserver/fxa'],
        'scope': ['profile'],
        'state': ['myfxastate:{next_path}'.format(next_path=next_path)],
    }


def test_unicode_next_path():
    path = u'/en-US/føø/bãr'
    request = RequestFactory().get(path)
    request.session = {}
    url = utils.default_fxa_login_url(request)
    state = urlparse.parse_qs(urlparse.urlparse(url).query)['state'][0]
    next_path = urlsafe_b64decode(state.split(':')[1] + '===')
    assert next_path.decode('utf-8') == path


@mock.patch('olympia.accounts.utils.default_fxa_login_url')
def test_redirect_for_login(default_fxa_login_url):
    login_url = 'https://example.com/login'
    default_fxa_login_url.return_value = login_url
    request = mock.MagicMock()
    response = utils.redirect_for_login(request)
    default_fxa_login_url.assert_called_with(request)
    assert response['location'] == login_url


class TestProcessSqsQueue(TestCase):

    @mock.patch('olympia.accounts.utils.process_fxa_event')
    @mock.patch('boto3.client')
    def test_process_sqs_queue(self, client, process_fxa_event):
        messages = [
            {'Body': 'foo', 'ReceiptHandle': '$$$'}, {'Body': 'bar'}, None,
            {'Body': 'thisonetoo'}]
        sqs = mock.MagicMock(
            **{'receive_message.side_effect': [{'Messages': messages}]})
        delete_mock = mock.MagicMock()
        sqs.delete_message = delete_mock
        client.return_value = sqs

        with self.assertRaises(StopIteration):
            utils.process_sqs_queue(
                queue_url='https://sqs.nowh-ere.aws.com/123456789/')

        client.assert_called()
        client.assert_called_with(
            'sqs', region_name='nowh-ere'
        )
        process_fxa_event.assert_called()
        # The 'None' in messages would cause an exception, but it should be
        # handled, and the remaining message(s) still processed.
        process_fxa_event.assert_has_calls(
            [mock.call('foo'), mock.call('bar'), mock.call('thisonetoo')])
        delete_mock.assert_called_once()  # Receipt handle is present in foo.
        delete_mock.assert_called_with(
            QueueUrl='https://sqs.nowh-ere.aws.com/123456789/',
            ReceiptHandle='$$$')


def totimestamp(datetime_obj):
    return time.mktime(datetime_obj.timetuple())


class TestProcessFxAEvent(TestCase):
    body = json.dumps({'Message': json.dumps(
        {'email': 'new-email@example.com', 'event': 'primaryEmailChanged',
         'uid': 'ABCDEF012345689',
         'ts': totimestamp(datetime(2017, 10, 11))})})

    def test_success_integration(self):
        user = user_factory(email='old-email@example.com',
                            fxa_id='ABCDEF012345689')
        process_fxa_event(self.body)
        user.reload()
        assert user.email == 'new-email@example.com'
        assert user.email_changed == datetime(2017, 10, 11, 0, 0)

    @mock.patch('olympia.accounts.utils.primary_email_change_event.delay')
    def test_success(self, primary_email_change_event):
        process_fxa_event(self.body)
        primary_email_change_event.assert_called()
        primary_email_change_event.assert_called_with(
            'new-email@example.com', 'ABCDEF012345689', datetime(2017, 10, 11))

    @mock.patch('olympia.accounts.utils.primary_email_change_event.delay')
    def test_malformed_body_doesnt_throw(self, primary_email_change_event):
        process_fxa_event('')
        process_fxa_event(json.dumps({'Message': ''}))
        process_fxa_event(json.dumps({'Message': 'ddfdfd'}))
        # No timestamp
        process_fxa_event(json.dumps({'Message': json.dumps(
            {'email': 'foo@baa', 'event': 'primaryEmailChanged',
             'uid': '999'})}))
        # Not a supported event type
        process_fxa_event(json.dumps({'Message': json.dumps(
            {'email': 'foo@baa', 'event': 'not-an-event', 'uid': '999',
             'ts': totimestamp(datetime.now())})}))
        primary_email_change_event.assert_not_called()
