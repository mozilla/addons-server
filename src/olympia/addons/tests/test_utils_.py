from datetime import timedelta

from django.forms import ValidationError

import pytest
from freezegun import freeze_time

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.users.models import Group, GroupUser

from ..utils import (
    RECOMMENDATIONS,
    DeleteTokenSigner,
    get_addon_recommendations,
    get_filtered_fallbacks,
    verify_mozilla_trademark,
)


@pytest.mark.django_db
@pytest.mark.parametrize(
    'name, allowed, give_permission',
    (
        ('Fancy new Add-on', True, False),
        # We allow the 'for ...' postfix to be used
        ('Fancy new Add-on for Firefox', True, False),
        ('Fancy new Add-on for Mozilla', True, False),
        # But only the postfix
        ('Fancy new Add-on for Firefox Browser', False, False),
        ('For Firefox fancy new add-on', False, False),
        # But users with the TRADEMARK_BYPASS permission are allowed
        ('Firefox makes everything better', False, False),
        ('Firefox makes everything better', True, True),
        ('Mozilla makes everything better', True, True),
        # A few more test-cases...
        ('Firefox add-on for Firefox', False, False),
        ('Firefox add-on for Firefox', True, True),
        ('Foobarfor Firefox', False, False),
        ('Better Privacy for Firefox!', True, False),
        ('Firefox awesome for Mozilla', False, False),
        ('Firefox awesome for Mozilla', True, True),
    ),
)
def test_verify_mozilla_trademark(name, allowed, give_permission):
    user = user_factory()
    if give_permission:
        group = Group.objects.create(name=name, rules='Trademark:Bypass')
        GroupUser.objects.create(group=group, user=user)

    if not allowed:
        with pytest.raises(ValidationError) as exc:
            verify_mozilla_trademark(name, user)
        assert exc.value.message == (
            'Add-on names cannot contain the Mozilla or Firefox trademarks.'
        )
    else:
        verify_mozilla_trademark(name, user)


class TestGetAddonRecommendations(TestCase):
    def setUp(self):
        self.a101 = addon_factory(id=101, guid='101@mozilla')
        addon_factory(id=102, guid='102@mozilla')
        addon_factory(id=103, guid='103@mozilla')
        addon_factory(id=104, guid='104@mozilla')

        self.recommendation_guids = [
            '101@mozilla',
            '102@mozilla',
            '103@mozilla',
            '104@mozilla',
        ]

    def test_not_recommended(self):
        recommendations = get_addon_recommendations('a@b')
        # It returns the first four fallback recommendations
        assert recommendations == RECOMMENDATIONS[:4]

    def test_get_filtered_fallbacks(self):
        # Fallback filters out the current guid if it exists in RECOMMENDATIONS
        recommendations = get_filtered_fallbacks(RECOMMENDATIONS[2])
        assert RECOMMENDATIONS[2] not in recommendations
        assert len(recommendations) == 4


@freeze_time(as_kwarg='frozen_time')
def test_delete_token_signer(frozen_time=None):
    signer = DeleteTokenSigner()
    addon_id = 1234
    token = signer.generate(addon_id)
    # generated token is valid
    assert signer.validate(token, addon_id)
    # generating with the same addon_id at the same time returns the same value
    assert token == signer.generate(addon_id)
    # generating with a different addon_id at the same time returns a different value
    assert token != signer.generate(addon_id + 1)
    # and the addon_id must match for it to be a valid token
    assert not signer.validate(token, addon_id + 1)

    # token is valid for 60 seconds so after 59 is still valid
    frozen_time.tick(timedelta(seconds=59))
    assert signer.validate(token, addon_id)

    # but not after 60 seconds
    frozen_time.tick(timedelta(seconds=2))
    assert not signer.validate(token, addon_id)
