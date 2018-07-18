# -*- coding: utf-8 -*-
from django.conf import settings

import mock
import pytest

from olympia.amo.tests import TestCase, user_factory
from olympia.users.models import DeniedName, UserProfile
from olympia.users.utils import (
    UnsubscribeCode,
    autocreate_username,
    system_addon_submission_allowed,
)


def test_email_unsubscribe_code_parse():
    email = 'nobody@mozîlla.org'
    token, hash_ = UnsubscribeCode.create(email)

    r_email = UnsubscribeCode.parse(token, hash_)
    assert email == r_email

    # A bad token or hash raises ValueError
    with pytest.raises(ValueError):
        UnsubscribeCode.parse(token, hash_[:-5])
    with pytest.raises(ValueError):
        UnsubscribeCode.parse(token[5:], hash_)


class TestAutoCreateUsername(TestCase):
    def test_invalid_characters(self):
        assert autocreate_username('testaccount+slug') == ('testaccountslug')

    def test_empty_username_is_a_random_hash(self):
        un = autocreate_username('.+')  # this shouldn't happen but it could!
        assert len(un) and not un.startswith('.+'), 'Unexpected: %s' % un

    def test_denied(self):
        DeniedName.objects.create(name='firefox')
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


system_guids = pytest.mark.parametrize(
    'guid',
    ['foo@mozilla.org', 'baa@shield.mozilla.org', 'moo@pioneer.mozilla.org'],
)


@system_guids
@pytest.mark.django_db
def test_system_addon_submission_allowed_mozilla_allowed(guid):
    user = user_factory(email='firefox@mozilla.com')
    data = {'guid': guid}
    assert system_addon_submission_allowed(user, data)


@system_guids
@pytest.mark.django_db
def test_system_addon_submission_allowed_not_mozilla_not_allowed(guid):
    user = user_factory(email='waterbadger@notzilla.org')
    data = {'guid': guid}
    assert not system_addon_submission_allowed(user, data)
