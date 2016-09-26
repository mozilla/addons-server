# -*- coding: utf-8 -*-
import mock

from django.conf import settings

from olympia.amo.tests import TestCase
from olympia.users.models import BlacklistedName, UserProfile
from olympia.users.utils import autocreate_username, UnsubscribeCode


class TestEmailResetAndUnsubscribeCode(TestCase):

    def test_email_unsubscribe_code_parse(self):
        email = 'nobody@mozîlla.org'
        token, hash_ = UnsubscribeCode.create(email)

        r_email = UnsubscribeCode.parse(token, hash_)
        assert email == r_email

        # A bad token or hash raises ValueError
        self.assertRaises(ValueError, UnsubscribeCode.parse, token, hash_[:-5])
        self.assertRaises(ValueError, UnsubscribeCode.parse, token[5:], hash_)


class TestAutoCreateUsername(TestCase):

    def test_invalid_characters(self):
        assert autocreate_username('testaccount+slug') == (
            'testaccountslug')

    def test_empty_username_is_a_random_hash(self):
        un = autocreate_username('.+')  # this shouldn't happen but it could!
        assert len(un) and not un.startswith('.+'), 'Unexpected: %s' % un

    def test_blacklisted(self):
        BlacklistedName.objects.create(name='firefox')
        un = autocreate_username('firefox')
        assert un != 'firefox', 'Unexpected: %s' % un

    def test_too_long(self):
        un = autocreate_username('f' + 'u' * 255)
        assert not un.startswith('fuuuuuuuuuuuuuuuuuu'), 'Unexpected: %s' % un

    @mock.patch.object(settings, 'MAX_GEN_USERNAME_TRIES', 2)
    def test_too_many_tries(self):
        UserProfile.objects.create(username='base')
        UserProfile.objects.create(username='base2')
        un = autocreate_username('base')
        assert not un.startswith('base'), 'Unexpected: %s' % un

    def test_duplicate_username_counter(self):
        UserProfile.objects.create(username='existingname')
        UserProfile.objects.create(username='existingname2')
        assert autocreate_username('existingname') == 'existingname3'
