import json
import uuid
import io

from django.core.management import call_command

from unittest.mock import ANY, patch

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import addon_factory, TestCase, user_factory
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


class TestClearOldUserData(TestCase):
    def test_no_addons(self):
        recent_date = self.days_ago(2)
        old_date = self.days_ago((365 * 7) + 1)

        # old enough but not deleted
        recent_not_deleted = user_factory(
            last_login_ip='127.0.0.1', fxa_id='12345')
        recent_not_deleted.update(modified=recent_date)

        # Deleted but new
        new_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='67890')

        # Deleted and recent: last_login_ip, email, fxa_id must be cleared.
        recent_deleted_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcde')
        recent_deleted_user.update(modified=recent_date)

        # Deleted and recent but with some cleared data already null.
        recent_deleted_user_part = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id=None)
        recent_deleted_user_part.update(modified=recent_date)

        # recent and banned
        recent_banned_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcde',
            banned=recent_date)
        recent_banned_user.update(modified=recent_date)

        old_banned_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcde',
            banned=recent_date)
        old_banned_user.update(modified=old_date)

        call_command('clear_old_user_data')

        recent_not_deleted.reload()
        assert recent_not_deleted.last_login_ip == '127.0.0.1'
        assert recent_not_deleted.deleted is False
        assert recent_not_deleted.email
        assert recent_not_deleted.fxa_id
        assert recent_not_deleted.modified == recent_date

        new_user.reload()
        assert new_user.last_login_ip == '127.0.0.1'
        assert new_user.deleted is True
        assert new_user.email
        assert new_user.fxa_id

        recent_deleted_user.reload()
        assert recent_deleted_user.last_login_ip == ''
        assert recent_deleted_user.deleted is True
        assert not recent_deleted_user.email
        assert not recent_deleted_user.fxa_id
        assert recent_deleted_user.modified == recent_date

        recent_deleted_user_part.reload()
        assert recent_deleted_user_part.last_login_ip == ''
        assert recent_deleted_user_part.deleted is True
        assert not recent_deleted_user_part.email
        assert not recent_deleted_user_part.fxa_id
        assert recent_deleted_user_part.modified == recent_date

        recent_banned_user.reload()
        assert recent_banned_user.last_login_ip == '127.0.0.1'
        assert recent_banned_user.deleted is True
        assert recent_banned_user.email
        assert recent_banned_user.fxa_id
        assert recent_banned_user.banned

        old_banned_user.reload()
        assert old_banned_user.last_login_ip == ''
        assert old_banned_user.deleted is True
        assert not old_banned_user.email
        assert not old_banned_user.fxa_id
        assert old_banned_user.modified == old_date
        assert old_banned_user.banned

    def test_addon_devs(self):
        old_date = self.days_ago((365 * 7) + 1)

        # Old but not deleted
        old_not_deleted = user_factory(
            last_login_ip='127.0.0.1', fxa_id='12345')
        old_not_deleted.update(modified=old_date)
        old_not_deleted_addon = addon_factory(
            users=[old_not_deleted], status=amo.STATUS_DELETED)

        # Deleted but not old enough
        recent_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='67890')
        recent_user.update(modified=self.days_ago(365))
        recent_user_addon = addon_factory(
            users=[recent_user], status=amo.STATUS_DELETED)

        old_user = user_factory(deleted=True, fxa_id='dfdf')
        old_user.update(modified=old_date)
        old_user_addon = addon_factory(
            users=[old_user], status=amo.STATUS_DELETED)
        # this shouldn't happen but lets be safe
        not_deleted_addon = addon_factory(
            users=[old_user, user_factory()])

        # Old, has addons, but already has other data cleared
        old_data_cleared = user_factory(
            deleted=True, last_login_ip='', email=None, fxa_id=None)
        old_data_cleared.update(modified=old_date)
        old_data_cleared_addon = addon_factory(
            users=[old_data_cleared], status=amo.STATUS_DELETED)

        call_command('clear_old_user_data')

        old_not_deleted.reload()
        assert old_not_deleted.last_login_ip == '127.0.0.1'
        assert old_not_deleted.deleted is False
        assert old_not_deleted.email
        assert old_not_deleted.fxa_id
        assert old_not_deleted.modified == old_date
        assert old_not_deleted_addon.reload()

        recent_user.reload()
        assert recent_user.last_login_ip == '127.0.0.1'
        assert recent_user.deleted is True
        assert recent_user.email
        assert recent_user.fxa_id
        assert recent_user_addon.reload()

        old_user.reload()
        assert old_user.last_login_ip == ''
        assert old_user.deleted is True
        assert not old_user.email
        assert not old_user.fxa_id
        assert old_user.modified == old_date
        assert not Addon.unfiltered.filter(id=old_user_addon.id).exists()
        assert not_deleted_addon.reload()

        assert not Addon.unfiltered.filter(
            id=old_data_cleared_addon.id).exists()
