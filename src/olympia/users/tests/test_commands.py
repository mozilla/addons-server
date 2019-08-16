import json
import uuid
import io

from django.core.management import call_command

from unittest.mock import ANY, patch

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
        out = io.StringIO()
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


class TestClearOldLastLoginIp(TestCase):
    def test_basic(self):
        # Old but not deleted
        old_date = self.days_ago(366)
        user1 = user_factory(last_login_ip='127.0.0.1', banned=old_date)

        # Deleted but recent
        user2 = user_factory(
            last_login_ip='127.0.0.1', deleted=True, banned=self.days_ago(1))

        # Deleted and old: last_login_ip must be cleared.
        user3 = user_factory(
            last_login_ip='127.0.0.1', deleted=True, banned=old_date)

        call_command('clear_old_last_login_ip')

        user1.reload()
        assert user1.last_login_ip == '127.0.0.1'
        assert user1.deleted is False
        assert user1.banned == old_date

        user2.reload()
        assert user2.last_login_ip == '127.0.0.1'
        assert user2.deleted is True

        user3.reload()
        assert user3.last_login_ip == ''
        assert user3.deleted is True
        assert user3.banned == old_date
