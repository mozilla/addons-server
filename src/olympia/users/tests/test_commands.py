import json
import uuid

from StringIO import StringIO

from django.core.management import call_command

import pytest
from mock import ANY, patch

from olympia.amo.tests import TestCase, user_factory, addon_factory
from olympia.addons.models import AddonUser
from olympia.users.management.commands.createsuperuser import (
    Command as CreateSuperUser)
from olympia.users.models import UserProfile


@patch('olympia.users.management.commands.createsuperuser.input')
def test_createsuperuser_username_validation(input):
    responses = ['', 'myusername']
    input.side_effect = lambda *args: responses.pop(0)
    command = CreateSuperUser()
    assert command.get_value('username') == 'myusername'


@patch('olympia.users.management.commands.createsuperuser.input')
def test_createsuperuser_email_validation(input):
    responses = ['', 'myemail', 'me@mozilla.org']
    input.side_effect = lambda *args: responses.pop(0)
    command = CreateSuperUser()
    assert command.get_value('email') == 'me@mozilla.org'


class TestCreateSuperUser(TestCase):
    fixtures = ['users/test_backends']

    @patch('olympia.users.management.commands.createsuperuser.input')
    def test_creates_user(self, input):
        responses = {
            'Username: ': 'myusername',
            'Email: ': 'me@mozilla.org',
        }
        input.side_effect = lambda label: responses[label]
        count = UserProfile.objects.count()
        CreateSuperUser().handle()
        assert UserProfile.objects.count() == count + 1
        user = UserProfile.objects.get(username='myusername')
        assert user.email == 'me@mozilla.org'

    def test_adds_supergroup(self):
        out = StringIO()
        fxa_id = uuid.uuid4().hex
        call_command(
            'createsuperuser',
            interactive=False,
            username='myusername',
            email='me@mozilla.org',
            add_to_supercreate_group=True,
            fxa_id=fxa_id,
            stdout=out)

        user = UserProfile.objects.get(username='myusername')
        assert user.email == 'me@mozilla.org'
        assert user.read_dev_agreement
        assert user.groups.filter(rules='Accounts:SuperCreate').exists()

        response = json.loads(out.getvalue())

        assert response == {
            'username': 'myusername',
            'email': 'me@mozilla.org',
            'api-key': ANY,
            'api-secret': ANY,
            'fxa-id': fxa_id,
        }


@pytest.mark.django_db
def test_sync_basket_no_developers():
    """We only sync add-on developers with basket."""
    user_factory()

    assert UserProfile.objects.count() == 1
    assert AddonUser.objects.count() == 0

    with patch('basket.base.request', autospec=True) as request_call:
        call_command('sync_basket')

    assert not request_call.called


@pytest.mark.django_db()
def test_sync_basket_only_developers_synced():
    """We only sync add-on developers with basket."""
    user_factory()
    developer = user_factory()
    addon_factory(users=[developer])

    assert UserProfile.objects.count() == 2
    assert AddonUser.objects.count() == 1

    with patch('basket.base.request', autospec=True) as request_call:
        request_call.return_value = {
            'status': 'ok', 'token': '123',
            'newsletters': ['announcements']}

        call_command('sync_basket')

    assert request_call.called
    request_call.assert_called_once_with(
        'get', 'lookup-user',
        headers={'x-api-key': 'testkey'},
        params={'email': developer.email})
