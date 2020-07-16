# -*- coding: utf-8 -*-
import pytest

from olympia.amo.tests import user_factory
from olympia.users.utils import (
    UnsubscribeCode, system_addon_submission_allowed)


def test_email_unsubscribe_code_parse():
    email = u'nobody@mozîlla.org'
    token, hash_ = UnsubscribeCode.create(email)

    r_email = UnsubscribeCode.parse(token, hash_)
    assert email == r_email

    # A bad token or hash raises ValueError
    with pytest.raises(ValueError):
        UnsubscribeCode.parse(token, hash_[:-5])
    with pytest.raises(ValueError):
        UnsubscribeCode.parse(token[5:], hash_)


system_guids = pytest.mark.parametrize('guid', [
    'foø@mozilla.org', 'baa@shield.mozilla.org', 'moo@pioneer.mozilla.org',
    'blâh@mozilla.com', 'foø@Mozilla.Org', 'addon@shield.moZilla.com',
    'baa@ShielD.MozillA.OrG', 'moo@PIONEER.mozilla.org', 'blâh@MOZILLA.COM',
    'flop@search.mozilla.org', 'user@mozillaonline.com',
    'tester@MoZiLlAoNlInE.CoM'
])


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
