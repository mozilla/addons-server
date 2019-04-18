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
    u'foø@mozilla.org', u'baa@shield.mozilla.org', u'moo@pioneer.mozilla.org',
    u'blâh@mozilla.com', u'foø@Mozilla.Org', u'baa@ShielD.MozillA.OrG',
    u'moo@PIONEER.mozilla.org', u'blâh@MOZILLA.COM'])


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
