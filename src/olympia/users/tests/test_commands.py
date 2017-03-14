import json
from StringIO import StringIO

from mock import patch, ANY
from django.core.management import call_command

from olympia.amo.tests import TestCase, user_factory
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
        call_command(
            'createsuperuser',
            interactive=False,
            username='myusername',
            email='me@mozilla.org',
            add_to_supercreate_group=True,
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
            'api-secret': ANY
        }


class TestBackFillAuthId(TestCase):
    def test_backfill(self):
        user_without = user_factory(auth_id=None)
        user_with = user_factory()

        old_auth_id = user_with.auth_id
        assert user_with.auth_id
        assert user_without.auth_id is None

        call_command('backfill_auth_id_for_existing_users')
        user_without.reload()
        user_with.reload()
        assert user_with.auth_id == old_auth_id
        assert user_without.auth_id
        assert user_without.auth_id != user_with.auth_id
