import os.path

from StringIO import StringIO

from django.conf import settings
from django.core.management import call_command

from olympia.amo.tests import TestCase, user_factory
from olympia.api.models import APIKey


class TestRevokeAPIKeys(TestCase):
    def setUp(self):
        self.csv_path = os.path.join(
            settings.ROOT, 'src', 'olympia', 'api', 'tests', 'assets',
            'test-revoke-api-keys.csv')

    def test_api_key_does_not_exist(self):
        user = user_factory()
        # The test csv does not contain an entry for this user.
        apikey = APIKey.new_jwt_credentials(user=user)
        old_secret = apikey.secret
        stdout = StringIO()
        call_command('revoke_api_keys', self.csv_path, stdout=stdout)
        stdout.seek(0)
        output = stdout.readlines()
        assert output[0] == (
            'Ignoring APIKey user:12345:666, it does not exist.\n')
        assert output[1] == (
            'Ignoring APIKey user:67890:333, it does not exist.\n')

        # APIKey is still active, secret hasn't changed, there are no
        # additional APIKeys.
        apikey.reload()
        assert apikey.secret == old_secret
        assert apikey.is_active
        assert APIKey.objects.filter(user=user).count() == 1

    def test_api_key_already_inactive(self):
        user = user_factory(id=67890)
        # The test csv contains an entry with this user and the "right" secret.
        right_secret = (
            'ab2228544a061cb2af21af97f637cc58e1f8340196f1ddc3de329b5974694b26')
        apikey = APIKey.objects.create(
            key='user:{}:{}'.format(user.pk, '333'), secret=right_secret,
            user=user, is_active=None)  # inactive APIKey.
        stdout = StringIO()
        call_command('revoke_api_keys', self.csv_path, stdout=stdout)
        stdout.seek(0)
        output = stdout.readlines()
        assert output[0] == (
            'Ignoring APIKey user:12345:666, it does not exist.\n')
        assert output[1] == (
            'Ignoring APIKey user:67890:333, it does not exist.\n')

        # APIKey is still active, secret hasn't changed, there are no
        # additional APIKeys.
        apikey.reload()
        assert apikey.secret == right_secret
        assert apikey.is_active is None
        assert APIKey.objects.filter(user=user).count() == 1

    def test_api_key_has_wrong_secret(self):
        user = user_factory(id=12345)
        # The test csv contains an entry with this user and the "wrong" secret.
        right_secret = (
            'ab2228544a061cb2af21af97f637cc58e1f8340196f1ddc3de329b5974694b26')
        apikey = APIKey.objects.create(
            key='user:{}:{}'.format(user.pk, '666'), secret=right_secret,
            user=user, is_active=True)
        stdout = StringIO()
        call_command('revoke_api_keys', self.csv_path, stdout=stdout)
        stdout.seek(0)
        output = stdout.readlines()
        assert output[0] == (
            'Ignoring APIKey user:12345:666, secret differs.\n')
        assert output[1] == (
            'Ignoring APIKey user:67890:333, it does not exist.\n')

        # API key is still active, secret hasn't changed, there are no
        # additional APIKeys.
        apikey.reload()
        assert apikey.secret == right_secret
        assert apikey.is_active
        assert APIKey.objects.filter(user=user).count() == 1

    def test_api_key_should_be_revoked(self):
        user = user_factory(id=67890)
        # The test csv contains an entry with this user and the "right" secret.
        right_secret = (
            'ab2228544a061cb2af21af97f637cc58e1f8340196f1ddc3de329b5974694b26')
        apikey = APIKey.objects.create(
            key='user:{}:{}'.format(user.pk, '333'), secret=right_secret,
            user=user, is_active=True)
        stdout = StringIO()
        call_command('revoke_api_keys', self.csv_path, stdout=stdout)
        stdout.seek(0)
        output = stdout.readlines()
        assert output[0] == (
            'Ignoring APIKey user:12345:666, it does not exist.\n')
        assert output[1] == (
            'Revoked APIKey user:67890:333.\n')
        assert output[2] == (
            'Ignoring APIKey garbage, it does not exist.\n')
        assert output[3] == (
            'Done. Revoked 1 keys out of 3 entries.\n')

        # API key is now inactive, secret hasn't changed, the other user api
        # key is still there, there are no additional APIKeys.
        apikey.reload()
        assert apikey.secret == right_secret
        assert apikey.is_active is None
        assert APIKey.objects.filter(user=user).count() == 2
        assert APIKey.objects.filter(user=user, is_active=True).count() == 1
