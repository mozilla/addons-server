import io
import json
import os
import re
import tempfile
import uuid
from ipaddress import IPv4Address
from unittest.mock import ANY, patch

from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command

from celery.result import EagerResult
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog, IPLog
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.utils import SafeStorage
from olympia.users.management.commands.createsuperuser import Command as CreateSuperUser
from olympia.users.models import (
    RESTRICTION_TYPES,
    DisposableEmailDomainRestriction,
    EmailUserRestriction,
    UserProfile,
    UserRestrictionHistory,
)


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


@override_switch('enable-addons-hard-deletion', active=True)
class TestClearOldUserData(TestCase):
    def create_ip_log(self, user):
        # Note: this is a dummy log that doesn't have store_ip=True on
        # purpose, to ensure we directly use IPLog when it comes to
        # deletion - so even if we change our minds about storing ips for
        # a given action after a while, we'll still correctly clear the old
        # data when it's time to do so.
        activity = ActivityLog.objects.create(amo.LOG.CUSTOM_TEXT, 'hi', user=user)
        IPLog.objects.create(activity_log=activity, ip_address_binary='127.0.0.56')

    def test_no_addons(self):
        recent_date = self.days_ago(2)
        old_date = self.days_ago((365 * 7) + 1)

        # old enough but not deleted
        recent_not_deleted = user_factory(last_login_ip='127.0.0.1', fxa_id='12345')
        recent_not_deleted.update(modified=recent_date)
        self.create_ip_log(recent_not_deleted)

        # Deleted but new
        new_user = user_factory(last_login_ip='127.0.0.1', deleted=True, fxa_id='67890')
        self.create_ip_log(new_user)

        # Deleted and recent: last_login_ip, email, fxa_id must be cleared.
        recent_deleted_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcdef1234'
        )
        recent_deleted_user.update(modified=recent_date)
        self.create_ip_log(recent_deleted_user)

        # Deleted and recent but with some cleared data already null.
        recent_deleted_user_part = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id=None
        )
        recent_deleted_user_part.update(modified=recent_date)
        self.create_ip_log(recent_deleted_user_part)

        # recent and banned
        recent_banned_user = user_factory(
            last_login_ip='127.0.0.1',
            deleted=True,
            fxa_id='abcdef4567',
            banned=recent_date,
        )
        recent_banned_user.update(modified=recent_date)
        self.create_ip_log(recent_banned_user)

        old_banned_user = user_factory(
            last_login_ip='127.0.0.1',
            deleted=True,
            fxa_id='abcdef8901',
            banned=recent_date,
        )
        old_banned_user.update(modified=old_date)
        self.create_ip_log(old_banned_user)

        call_command('clear_old_user_data')

        recent_not_deleted.reload()
        assert recent_not_deleted.last_login_ip == '127.0.0.1'
        assert recent_not_deleted.deleted is False
        assert recent_not_deleted.email
        assert recent_not_deleted.fxa_id
        assert recent_not_deleted.modified == recent_date
        assert recent_not_deleted.activitylog_set.count() == 1
        assert IPLog.objects.filter(
            activity_log__user=recent_not_deleted
        ).get().ip_address_binary == IPv4Address('127.0.0.56')

        new_user.reload()
        assert new_user.last_login_ip == '127.0.0.1'
        assert new_user.deleted is True
        assert new_user.email
        assert new_user.fxa_id
        assert new_user.activitylog_set.count() == 1
        assert IPLog.objects.filter(
            activity_log__user=new_user
        ).get().ip_address_binary == IPv4Address('127.0.0.56')

        recent_deleted_user.reload()
        assert recent_deleted_user.last_login_ip == ''
        assert recent_deleted_user.deleted is True
        assert not recent_deleted_user.email
        assert not recent_deleted_user.fxa_id
        assert recent_deleted_user.modified == recent_date
        assert recent_deleted_user.activitylog_set.count() == 1
        assert not IPLog.objects.filter(activity_log__user=recent_deleted_user).exists()

        recent_deleted_user_part.reload()
        assert recent_deleted_user_part.last_login_ip == ''
        assert recent_deleted_user_part.deleted is True
        assert not recent_deleted_user_part.email
        assert not recent_deleted_user_part.fxa_id
        assert recent_deleted_user_part.modified == recent_date
        assert recent_deleted_user_part.activitylog_set.count() == 1
        assert not IPLog.objects.filter(
            activity_log__user=recent_deleted_user_part
        ).exists()

        recent_banned_user.reload()
        assert recent_banned_user.last_login_ip == '127.0.0.1'
        assert recent_banned_user.deleted is True
        assert recent_banned_user.email
        assert recent_banned_user.fxa_id
        assert recent_banned_user.banned
        assert recent_banned_user.activitylog_set.count() == 1
        assert IPLog.objects.filter(
            activity_log__user=recent_banned_user
        ).get().ip_address_binary == IPv4Address('127.0.0.56')

        old_banned_user.reload()
        assert old_banned_user.last_login_ip == ''
        assert old_banned_user.deleted is True
        assert not old_banned_user.email
        assert not old_banned_user.fxa_id
        assert old_banned_user.modified == old_date
        assert old_banned_user.banned
        assert old_banned_user.activitylog_set.count() == 1
        assert not IPLog.objects.filter(activity_log__user=old_banned_user).exists()

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
            last_login_ip='127.0.0.1', deleted=True, fxa_id='abcd'
        )
        recent_deleted_user.update(modified=recent_date)
        urh2 = UserRestrictionHistory.objects.create(
            user=recent_deleted_user,
            restriction=2,
            ip_address='128.1.2.3',
            last_login_ip='128.4.5.6',
        )

        old_banned_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='ef123', banned=recent_date
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
        self.create_ip_log(old_not_deleted)
        old_not_deleted_addon = addon_factory(
            users=[old_not_deleted], status=amo.STATUS_DELETED
        )

        # Deleted but not old enough
        recent_user = user_factory(
            last_login_ip='127.0.0.1', deleted=True, fxa_id='67890'
        )
        recent_user.update(modified=self.days_ago(365))
        self.create_ip_log(recent_user)
        recent_user_addon = addon_factory(
            users=[recent_user], status=amo.STATUS_DELETED
        )

        old_user = user_factory(deleted=True, fxa_id='dfdf')
        old_user.update(modified=old_date)
        self.create_ip_log(old_user)
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
        self.create_ip_log(old_banned_user)
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
        assert IPLog.objects.filter(
            activity_log__user=old_not_deleted
        ).get().ip_address_binary == IPv4Address('127.0.0.56')

        recent_user.reload()
        assert recent_user.last_login_ip == '127.0.0.1'
        assert recent_user.deleted is True
        assert recent_user.email
        assert recent_user.fxa_id
        assert recent_user_addon.reload()
        assert IPLog.objects.filter(
            activity_log__user=recent_user
        ).get().ip_address_binary == IPv4Address('127.0.0.56')

        old_user.reload()
        assert old_user.last_login_ip == ''
        assert old_user.deleted is True
        assert not old_user.email
        assert not old_user.fxa_id
        assert old_user.modified == old_date
        assert not Addon.unfiltered.filter(id=old_user_addon.id).exists()
        assert no_longer_owner_addon.reload()
        assert not IPLog.objects.filter(activity_log__user=old_user).exists()

        assert not Addon.unfiltered.filter(id=old_data_cleared_addon.id).exists()

        old_banned_user.reload()
        assert old_banned_user.last_login_ip == ''
        assert old_banned_user.deleted is True
        assert not old_banned_user.email
        assert not old_banned_user.fxa_id
        assert old_banned_user.modified == old_date
        assert old_banned_user.banned
        assert not Addon.unfiltered.filter(id=old_banned_user_addon.id).exists()
        assert not IPLog.objects.filter(activity_log__user=old_banned_user).exists()

        # But check that no_longer_owner_addon is deleted eventually
        old_not_deleted.update(deleted=True)
        call_command('clear_old_user_data')
        old_not_deleted.reload()
        assert not old_not_deleted.email
        assert not Addon.unfiltered.filter(id=old_not_deleted_addon.id).exists()
        assert not Addon.unfiltered.filter(id=no_longer_owner_addon.id).exists()

    @override_switch('enable-addons-hard-deletion', active=False)
    def test_waffle_off(self):
        old_date = self.days_ago((365 * 7) + 1)
        old_user = user_factory(deleted=True, fxa_id='dfdf')
        old_user.update(modified=old_date)
        self.create_ip_log(old_user)
        old_user_addon = addon_factory(users=[old_user], status=amo.STATUS_DELETED)
        call_command('clear_old_user_data')
        old_user.reload()
        assert old_user.last_login_ip == ''
        assert old_user.deleted is True
        assert not old_user.email
        assert not old_user.fxa_id
        assert old_user.modified == old_date
        assert not IPLog.objects.filter(activity_log__user=old_user).exists()

        # Waffle switch is off so we kept the add-on data.
        assert Addon.unfiltered.filter(pk=old_user_addon.pk).exists()


class TestMigrateUserPhotos(TestCase):
    def setUp(self):
        self.storage = SafeStorage(root_setting='MEDIA_ROOT', rel_location='userpics')
        self.user = user_factory()
        self.deleted_user = user_factory(deleted=True)

        self.old_picture_path = (
            f'{self.get_old_picture_dir(self.user)}/{self.user.pk}.png'
        )
        self.old_picture_path_original = (
            f'{self.get_old_picture_dir(self.user)}/{self.user.pk}_original.png'
        )

        self.old_deleted_picture_path = (
            f'{self.get_old_picture_dir(self.deleted_user)}/{self.deleted_user.pk}.png'
        )
        self.old_deleted_picture_path_original = (
            f'{self.get_old_picture_dir(self.deleted_user)}/'
            f'{self.deleted_user.pk}_original.png'
        )

        self.garbage_path = 'somewhere/deep/whatever.png'
        self.other_garbage_path = f'{self.get_old_picture_dir(self.user)}/føøøøø.png'
        self.yet_another_garbage_path = (
            f'{self.get_old_picture_dir(self.user)}/{self.user.pk}_nopé.bin'
        )

        # Files that need to be migrated.
        self.storage.save(self.old_picture_path, ContentFile('xxx'))
        self.storage.save(self.old_picture_path_original, ContentFile('yyy'))

        # Orphaned/garbage files that should be removed.
        self.storage.save(self.garbage_path, ContentFile('ggg'))
        self.storage.save(self.other_garbage_path, ContentFile('ŋŋŋ'))
        self.storage.save(self.yet_another_garbage_path, ContentFile('nnn'))
        self.storage.save(self.old_deleted_picture_path, ContentFile('aaa'))
        self.storage.save(self.old_deleted_picture_path_original, ContentFile('bbb'))

    def get_old_picture_dir(self, user):
        split_id = re.match(r'((\d*?)(\d{0,3}?))\d{1,3}$', str(user.pk))
        return os.path.join(split_id.group(2) or '0', split_id.group(1) or '0')

    def test_migrate(self):
        old_paths = (
            self.old_picture_path,
            self.old_picture_path_original,
            self.old_deleted_picture_path,
            self.old_deleted_picture_path_original,
            self.garbage_path,
            self.other_garbage_path,
            self.yet_another_garbage_path,
        )
        for path in old_paths:
            assert self.storage.exists(path)
        # These should not exist since we haven't ran the migration yet.
        assert not self.storage.exists(self.user.picture_path)
        assert not self.storage.exists(self.user.picture_path_original)

        call_command('migrate_user_photos')

        # Now, every old paths should be gone and only the non-deleted user
        # photo should have been migrated.
        for path in old_paths:
            assert not self.storage.exists(path)
        assert self.storage.exists(self.user.picture_path)
        assert self.storage.exists(self.user.picture_path_original)
        assert self.storage.open(self.user.picture_path).read() == b'xxx'
        assert self.storage.open(self.user.picture_path_original).read() == b'yyy'
        assert set(self.storage.listdir(self.user.picture_dir)[1]) == {
            f'{self.user.pk}.png',
            f'{self.user.pk}_original.png',
        }

    def test_migrate_twice(self):
        self.test_migrate()
        # Running the migration command again shouldn't do anything.
        call_command('migrate_user_photos')


class TestBulkAddDisposableEmailDomains(TestCase):
    def test_missing_file_raises_command_error(self):
        """Test that the command raises CommandError if the file does not exist"""

        for file, message in [
            (None, 'Error: the following arguments are required: file'),
            ('none', 'File none does not exist'),
        ]:
            with self.assertRaises(CommandError) as e:
                args = ['bulk_add_disposable_domains']
                if file:
                    args.append(file)
                call_command(*args)
            assert message == e.exception.args[0]

    def test_valid_file_triggers_bulk_add(self):
        """Test that a valid CSV file triggers
        the bulk_add_disposable_email_domains task
        and creates DisposableDomainRestriction objects.
        """

        csv_content = (
            'Domain,Provider\n'
            'mailfast.pro,incognitomail.co\n'
            'foo.com,mail.tm\n'
            'mailpro.live,incognitomail.co\n'
        )

        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv') as tmp:
            tmp.write(csv_content)
            tmp.flush()
            tmp_path = tmp.name

            assert DisposableEmailDomainRestriction.objects.count() == 0

            call_command('bulk_add_disposable_domains', tmp_path)

        expected = [
            ('mailfast.pro', 'incognitomail.co'),
            ('foo.com', 'mail.tm'),
            ('mailpro.live', 'incognitomail.co'),
        ]
        for domain, provider in expected:
            assert DisposableEmailDomainRestriction.objects.filter(
                domain=domain, reason=f'Disposable email domain of {provider}'
            ).exists()

        assert DisposableEmailDomainRestriction.objects.count() == len(expected)

    def test_file_with_missing_columns(self):
        """Test that rows with missing columns are ignored or handled gracefully."""
        csv_content = (
            'Domain,Provider\n'
            'mailfast.pro,incognitomail.co\n'
            ',mail.tm\n'  # Missing domain
            'mailpro.live,incognitomail.co\n'
        )

        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv') as tmp:
            tmp.write(csv_content)
            tmp.flush()
            tmp_path = tmp.name

            assert DisposableEmailDomainRestriction.objects.count() == 0

            call_command('bulk_add_disposable_domains', tmp_path)

        expected = [
            ('mailfast.pro', 'incognitomail.co'),
            ('mailpro.live', 'incognitomail.co'),
        ]
        for domain, provider in expected:
            assert DisposableEmailDomainRestriction.objects.filter(
                domain=domain, reason=f'Disposable email domain of {provider}'
            ).exists()

        assert not DisposableEmailDomainRestriction.objects.filter(domain='').exists()
        assert DisposableEmailDomainRestriction.objects.count() == len(expected)

    def test_file_with_header_only(self):
        """Test that a file with only a header row does not trigger any additions."""
        csv_content = 'Domain,Provider\n'

        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv') as tmp:
            tmp.write(csv_content)
            tmp.flush()
            tmp_path = tmp.name

            call_command('bulk_add_disposable_domains', tmp_path)
            assert DisposableEmailDomainRestriction.objects.count() == 0

    @patch('olympia.users.management.commands.bulk_add_disposable_domains.logger')
    def test_bulk_add_result_is_printed(self, mock_logger):
        """result of bulk_add_disposable_email_domains task logged."""

        csv_content = (
            'Domain,Provider\n'
            'mailfast.pro,incognitomail.co\n'
            'mailpro.live,incognitomail.co\n'
        )

        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv') as tmp:
            tmp.write(csv_content)
            tmp.flush()
            tmp_path = tmp.name

            call_command('bulk_add_disposable_domains', tmp_path)
            result = mock_logger.info.call_args[0][0]
            assert isinstance(result, EagerResult)
            assert result.state == 'SUCCESS'

    def test_trims_domains_of_whitespace(self):
        """Test that domains with whitespace are trimmed."""
        csv_content = (
            'Domain,Provider\n'
            ' mailfast.pro  ,incognitomail.co\n'
            'foo.com,mail.tm\n'
            'mailpro.live,incognitomail.co\n'
        )

        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.csv') as tmp:
            tmp.write(csv_content)
            tmp.flush()
            tmp_path = tmp.name

            assert DisposableEmailDomainRestriction.objects.count() == 0

            call_command('bulk_add_disposable_domains', tmp_path)

        expected = [
            ('mailfast.pro', 'incognitomail.co'),
            ('foo.com', 'mail.tm'),
            ('mailpro.live', 'incognitomail.co'),
        ]
        for domain, provider in expected:
            assert DisposableEmailDomainRestriction.objects.filter(
                domain=domain, reason=f'Disposable email domain of {provider}'
            ).exists()


class TestRestrictBannedUsers(TestCase):
    def test_basic(self):
        not_banned = user_factory()
        banned = user_factory(banned=self.days_ago(42), deleted=True)
        assert not EmailUserRestriction.objects.filter(
            email_pattern=not_banned.email
        ).exists()
        call_command('process_users', task='restrict_banned_users')

        assert not EmailUserRestriction.objects.filter(
            email_pattern=not_banned.email
        ).exists()
        assert (
            EmailUserRestriction.objects.filter(email_pattern=banned.email).count() == 2
        )
        restriction = EmailUserRestriction.objects.filter(
            email_pattern=banned.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).get()
        assert (
            restriction.reason
            == f'Automatically added because of user {banned.pk} ban (backfill)'
        )
        restriction = EmailUserRestriction.objects.filter(
            email_pattern=banned.email,
            restriction_type=RESTRICTION_TYPES.RATING,
        ).get()
        assert (
            restriction.reason
            == f'Automatically added because of user {banned.pk} ban (backfill)'
        )

    def test_ignores_dupes_other_restriction_types(self):
        banned = user_factory(banned=self.days_ago(42), deleted=True)
        EmailUserRestriction.objects.create(
            email_pattern=banned.email,
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )
        call_command('process_users', task='restrict_banned_users')
        assert (
            EmailUserRestriction.objects.filter(email_pattern=banned.email).count() == 3
        )
        restriction = EmailUserRestriction.objects.filter(
            email_pattern=banned.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).get()
        assert (
            restriction.reason
            == f'Automatically added because of user {banned.pk} ban (backfill)'
        )
        restriction = EmailUserRestriction.objects.filter(
            email_pattern=banned.email,
            restriction_type=RESTRICTION_TYPES.RATING,
        ).get()
        assert (
            restriction.reason
            == f'Automatically added because of user {banned.pk} ban (backfill)'
        )

    def test_do_not_create_dupes_same_restriction_type(self):
        banned = user_factory(banned=self.days_ago(42), deleted=True)
        EmailUserRestriction.objects.create(
            email_pattern=banned.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
            reason='Already exists',
        )
        call_command('process_users', task='restrict_banned_users')
        assert (
            EmailUserRestriction.objects.filter(email_pattern=banned.email).count() == 2
        )
        restriction = EmailUserRestriction.objects.filter(
            email_pattern=banned.email,
            restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION,
        ).get()
        assert restriction.reason == 'Already exists'
        restriction = EmailUserRestriction.objects.filter(
            email_pattern=banned.email,
            restriction_type=RESTRICTION_TYPES.RATING,
        ).get()
        assert (
            restriction.reason
            == f'Automatically added because of user {banned.pk} ban (backfill)'
        )

    def test_normalization(self):
        banned = user_factory(
            email='foo.bar+alice@example.com', banned=self.days_ago(42), deleted=True
        )
        call_command('process_users', task='restrict_banned_users')
        restriction = EmailUserRestriction.objects.filter(
            email_pattern='foobar@example.com',
            restriction_type=RESTRICTION_TYPES.RATING,
        ).get()
        assert (
            restriction.reason
            == f'Automatically added because of user {banned.pk} ban (backfill)'
        )
