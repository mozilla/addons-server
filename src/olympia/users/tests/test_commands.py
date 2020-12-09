import json
import uuid
import io

from django.core.management import call_command

from unittest.mock import ANY, patch

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.users.management.commands.createsuperuser import Command as CreateSuperUser
from olympia.users.models import UserProfile, UserRestrictionHistory


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
            stdout=out,
        )

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
        recent_not_deleted = user_factory(last_login_ip='127.0.0.1', fxa_id='12345')
        recent_not_deleted.update(modified=recent_date)

        # Deleted but new
        new_user = user_factory(last_login_ip='127.0.0.1', deleted=True, fxa_id='67890')

        # Deleted and recent: last_login_ip, email, fxa_id must be cleared.
        recent_deleted_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcde'
        )
        recent_deleted_user.update(modified=recent_date)

        # Deleted and recent but with some cleared data already null.
        recent_deleted_user_part = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id=None
        )
        recent_deleted_user_part.update(modified=recent_date)

        # recent and banned
        recent_banned_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcde', banned=recent_date
        )
        recent_banned_user.update(modified=recent_date)

        old_banned_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcde', banned=recent_date
        )
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

    def test_user_restriction_history_cleared_too(self):
        recent_date = self.days_ago(2)
        old_date = self.days_ago((365 * 7) + 1)

        # old enough but not deleted
        recent_not_deleted = user_factory(last_login_ip='127.0.0.1', fxa_id='12345')
        recent_not_deleted.update(modified=recent_date)
        urh0 = UserRestrictionHistory.objects.create(
            user=recent_not_deleted,
            restriction=0,
            ip_address='127.1.2.3',
            last_login_ip='127.4.5.6',
        )

        # Deleted but new
        new_user = user_factory(last_login_ip='127.0.0.1', deleted=True, fxa_id='67890')
        urh1 = UserRestrictionHistory.objects.create(
            user=new_user,
            restriction=1,
            ip_address='127.1.2.3',
            last_login_ip='127.4.5.6',
        )

        # Deleted and recent: last_login_ip, email, fxa_id must be cleared.
        recent_deleted_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcde'
        )
        recent_deleted_user.update(modified=recent_date)
        urh2 = UserRestrictionHistory.objects.create(
            user=recent_deleted_user,
            restriction=2,
            ip_address='128.1.2.3',
            last_login_ip='128.4.5.6',
        )

        old_banned_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcde', banned=recent_date
        )
        old_banned_user.update(modified=old_date)
        urh3 = UserRestrictionHistory.objects.create(
            user=old_banned_user,
            restriction=3,
            ip_address='129.1.2.3',
            last_login_ip='129.4.5.6',
        )
        urh4 = UserRestrictionHistory.objects.create(
            user=old_banned_user,
            restriction=4,
            ip_address='130.1.2.3',
            last_login_ip='130.4.5.6',
        )

        call_command('clear_old_user_data')

        # these shouldn't have been touched because the users weren't cleared
        urh0.reload()
        assert urh0.ip_address != ''
        assert urh0.last_login_ip != ''
        urh1.reload()
        assert urh1.ip_address != ''
        assert urh1.last_login_ip != ''

        # these should have been cleared because the userprofiles were cleared
        urh2.reload()
        assert urh2.ip_address == ''
        assert urh2.last_login_ip == ''
        urh3.reload()
        assert urh3.ip_address == ''
        assert urh3.last_login_ip == ''
        urh4.reload()
        assert urh4.ip_address == ''
        assert urh4.last_login_ip == ''

    def test_addon_devs(self):
        old_date = self.days_ago((365 * 7) + 1)

        # Old but not deleted
        old_not_deleted = user_factory(last_login_ip='127.0.0.1', fxa_id='12345')
        old_not_deleted.update(modified=old_date)
        old_not_deleted_addon = addon_factory(
            users=[old_not_deleted], status=amo.STATUS_DELETED
        )

        # Deleted but not old enough
        recent_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='67890'
        )
        recent_user.update(modified=self.days_ago(365))
        recent_user_addon = addon_factory(
            users=[recent_user], status=amo.STATUS_DELETED
        )

        old_user = user_factory(deleted=True, fxa_id='dfdf')
        old_user.update(modified=old_date)
        old_user_addon = addon_factory(users=[old_user], status=amo.STATUS_DELETED)
        # Include an add-on that old_user _was_ an owner of, but now isn't.
        # Even if the addon is now deleted it shouldn't be hard-deleted with
        # old_user.
        no_longer_owner_addon = addon_factory(users=[old_user, old_not_deleted])
        no_longer_owner_addon.addonuser_set.get(user=old_user).delete()
        assert old_user not in list(no_longer_owner_addon.authors.all())
        assert UserProfile.objects.filter(
            addons=no_longer_owner_addon, id=old_user.id
        ).exists()
        no_longer_owner_addon.delete()

        # Old, has addons, but already has other data cleared
        old_data_cleared = user_factory(
            deleted=True, last_login_ip='', email=None, fxa_id=None
        )
        old_data_cleared.update(modified=old_date)
        old_data_cleared_addon = addon_factory(
            users=[old_data_cleared], status=amo.STATUS_DELETED
        )

        old_banned_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcde', banned=old_date
        )
        old_banned_user.update(modified=old_date)
        old_banned_user_addon = addon_factory(
            users=[old_banned_user], status=amo.STATUS_DISABLED
        )

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
        assert no_longer_owner_addon.reload()

        assert not Addon.unfiltered.filter(id=old_data_cleared_addon.id).exists()

        old_banned_user.reload()
        assert old_banned_user.last_login_ip == ''
        assert old_banned_user.deleted is True
        assert not old_banned_user.email
        assert not old_banned_user.fxa_id
        assert old_banned_user.modified == old_date
        assert old_banned_user.banned
        assert not Addon.unfiltered.filter(id=old_banned_user_addon.id).exists()

        # But check that no_longer_owner_addon is deleted eventually
        old_not_deleted.update(deleted=True)
        call_command('clear_old_user_data')
        old_not_deleted.reload()
        assert not old_not_deleted.email
        assert not Addon.unfiltered.filter(id=old_not_deleted_addon.id).exists()
        assert not Addon.unfiltered.filter(id=no_longer_owner_addon.id).exists()
