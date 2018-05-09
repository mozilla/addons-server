import json
import uuid

from StringIO import StringIO

from django.core.management import call_command

from mock import ANY, patch

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


class TestUpdateDeletedUsers(TestCase):

    def test_updates_deleted_metadata(self):
        user = user_factory(fxa_id='foobar', last_login_ip='192.168.1.1')

        call_command(
            'update_deleted_users',
            interactive=False)

        # Nothing happened, the user wasn't deleted
        user.refresh_from_db()
        assert user.fxa_id == 'foobar'

        user.delete()
        assert user.fxa_id is None
        assert user.last_login_ip == ''

        # Now set something and make sure `.delete` get's called again
        user.update(fxa_id='foobar', last_login_ip='192.168.1.1')

        call_command(
            'update_deleted_users',
            interactive=False)

        user.refresh_from_db()
        assert user.fxa_id is None
        assert user.last_login_ip == ''
