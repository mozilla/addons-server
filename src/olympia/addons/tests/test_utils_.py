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
    validate_addon_name,
)


@pytest.mark.django_db
@pytest.mark.parametrize(
    'name',
    (
        'Fancy new Add-on',
        # We allow the 'for ...' postfix to be used
        'Fancy new Add-on for Firefox',
        'Fancy new Add-on for Mozilla',
        'Better Privacy for Firefox!',
        # Right on the limit of what's acceptable for number of homoglyphs
        'BIlIbIlI Helper: BIlIbIlI.com AuxIlIary',
    ),
)
def test_validate_addon_name_allowed(name):
    user = user_factory()
    validate_addon_name(name, user)


@pytest.mark.django_db
@pytest.mark.parametrize(
    'name',
    (
        'Fancy new Add-on for Firefox Browser',
        'For Firefox shiny new add-on',
        'Firefox makes everything better',
        'Mozilla makes everything better',
        'Firefox add-on for Firefox',
        'Foobarfor Firefox',
        'F i r e f o x',
        'F î r \u0435fox',
        'FiRѐF0 x',
        'F i r \u0435 f o x',
        'F\u2800i r e f o x',
        'F\u2800 i r \u0435 f o x',
        'Fïrefox is great',
        'Foobarfor Firefox!',
        'Mozilla',
        'm0z1IIa',
        'Moziꙇꙇa',
        'Firefox awesome for Mozilla',
        'Firefox awesome for Mozilla',
    ),
)
def test_validate_addon_name_disallowed_without_permission(name):
    normal_user = user_factory()
    special_user = user_factory()
    group = Group.objects.create(name=name, rules='Trademark:Bypass')
    GroupUser.objects.create(group=group, user=special_user)

    # Validates with the permission.
    validate_addon_name(name, special_user)

    # Raises an error without.
    with pytest.raises(ValidationError) as exc:
        validate_addon_name(name, normal_user)
    assert exc.value.message == (
        'Add-on names cannot contain the Mozilla or Firefox trademarks.'
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    'name',
    (
        'l' * 17,  # Too many homoglyphs
        'l' * 50,  # Way too many homoglyphs!
    ),
)
def test_validate_addon_name_disallowed_no_matter_what(name):
    normal_user = user_factory()
    special_user = user_factory()
    group = Group.objects.create(name=name, rules='Trademark:Bypass')
    GroupUser.objects.create(group=group, user=special_user)

    # Raises an error without the permission...
    with pytest.raises(ValidationError) as exc:
        validate_addon_name(name, normal_user)
    assert exc.value.message == 'This name cannot be used.'

    # ... and also with it.
    with pytest.raises(ValidationError) as exc2:
        validate_addon_name(name, special_user)
    assert exc2.value.message == 'This name cannot be used.'


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
