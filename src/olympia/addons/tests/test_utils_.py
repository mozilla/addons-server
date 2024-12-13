from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.forms import ValidationError

import pytest
from freezegun import freeze_time

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.users.models import Group, GroupUser

from ..utils import (
    TAAR_LITE_FALLBACK_REASON_EMPTY,
    TAAR_LITE_FALLBACK_REASON_INVALID,
    TAAR_LITE_FALLBACK_REASON_TIMEOUT,
    TAAR_LITE_FALLBACKS,
    TAAR_LITE_OUTCOME_CURATED,
    TAAR_LITE_OUTCOME_REAL_FAIL,
    TAAR_LITE_OUTCOME_REAL_SUCCESS,
    DeleteTokenSigner,
    get_addon_recommendations,
    get_addon_recommendations_invalid,
    get_filtered_fallbacks,
    is_outcome_recommended,
    validate_version_number_is_gt_latest_signed_listed_version,
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


@mock.patch('django_statsd.clients.statsd.incr')
class TestGetAddonRecommendations(TestCase):
    def setUp(self):
        patcher = mock.patch('olympia.addons.utils.call_recommendation_server')
        self.recommendation_server_mock = patcher.start()
        self.addCleanup(patcher.stop)
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
        self.recommendation_server_mock.return_value = self.recommendation_guids

    def test_recommended(self, incr_mock):
        recommendations, outcome, reason = get_addon_recommendations('a@b', True)
        assert recommendations == self.recommendation_guids
        assert outcome == TAAR_LITE_OUTCOME_REAL_SUCCESS
        assert reason is None
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {}
        )
        assert incr_mock.call_count == 1
        assert incr_mock.call_args_list[0][0] == (
            'services.addon_recommendations.success',
        )

    def test_recommended_no_results(self, incr_mock):
        self.recommendation_server_mock.return_value = []
        recommendations, outcome, reason = get_addon_recommendations('a@b', True)
        assert recommendations == TAAR_LITE_FALLBACKS[:4]
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason is TAAR_LITE_FALLBACK_REASON_EMPTY
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {}
        )
        assert incr_mock.call_count == 1
        assert incr_mock.call_args_list[0][0] == (
            f'services.addon_recommendations.{TAAR_LITE_FALLBACK_REASON_EMPTY}',
        )
        # Fallback filters out the current guid if it exists in TAAR_LITE_FALLBACKS
        recommendations, _, _ = get_addon_recommendations(TAAR_LITE_FALLBACKS[0], True)
        assert recommendations == TAAR_LITE_FALLBACKS[1:]

    def test_recommended_timeout(self, incr_mock):
        self.recommendation_server_mock.return_value = None
        recommendations, outcome, reason = get_addon_recommendations('a@b', True)
        assert recommendations == TAAR_LITE_FALLBACKS[:4]
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason is TAAR_LITE_FALLBACK_REASON_TIMEOUT
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {}
        )
        assert incr_mock.call_count == 1
        assert incr_mock.call_args_list[0][0] == (
            f'services.addon_recommendations.{TAAR_LITE_FALLBACK_REASON_TIMEOUT}',
        )

    def test_not_recommended(self, incr_mock):
        recommendations, outcome, reason = get_addon_recommendations('a@b', False)
        assert not self.recommendation_server_mock.called
        assert recommendations == TAAR_LITE_FALLBACKS[:4]
        assert outcome == TAAR_LITE_OUTCOME_CURATED
        assert reason is None
        assert incr_mock.call_count == 0

    def test_invalid_fallback(self, incr_mock):
        recommendations, outcome, reason = get_addon_recommendations_invalid()
        assert not self.recommendation_server_mock.called
        assert recommendations == TAAR_LITE_FALLBACKS[:4]
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason == TAAR_LITE_FALLBACK_REASON_INVALID
        assert incr_mock.call_count == 0
        # Fallback filters out the current guid if it exists in TAAR_LITE_FALLBACKS
        recommendations, _, _ = get_addon_recommendations_invalid(TAAR_LITE_FALLBACKS[0])
        assert recommendations == TAAR_LITE_FALLBACKS[1:]
    
    def test_get_filtered_fallbacks(self, _):
        # Fallback filters out the current guid if it exists in TAAR_LITE_FALLBACKS
        recommendations = get_filtered_fallbacks(TAAR_LITE_FALLBACKS[2])
        assert recommendations == TAAR_LITE_FALLBACKS[:2] + TAAR_LITE_FALLBACKS[3:]
        # Fallback returns the first four if it does not.
        recommendations, outcome, reason = get_addon_recommendations_invalid('random-guid')
        assert recommendations == TAAR_LITE_FALLBACKS[:4]

    def test_is_outcome_recommended(self, incr_mock):
        assert is_outcome_recommended(TAAR_LITE_OUTCOME_REAL_SUCCESS)
        assert not is_outcome_recommended(TAAR_LITE_OUTCOME_REAL_FAIL)
        assert not is_outcome_recommended(TAAR_LITE_OUTCOME_CURATED)
        assert not self.recommendation_server_mock.called
        assert incr_mock.call_count == 0


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


@pytest.mark.django_db
def test_validate_version_number_is_gt_latest_signed_listed_version():
    addon = addon_factory(version_kw={'version': '123.0'}, file_kw={'is_signed': True})
    # add an unlisted version, which should be ignored.
    latest_unlisted = version_factory(
        addon=addon,
        version='124',
        channel=amo.CHANNEL_UNLISTED,
        file_kw={'is_signed': True},
    )
    # Version number is greater, but doesn't matter, because the check is listed only.
    assert latest_unlisted.version > addon.current_version.version

    # version number isn't greater (its the same).
    assert validate_version_number_is_gt_latest_signed_listed_version(addon, '123') == (
        'Version 123 must be greater than the previous approved version 123.0.'
    )
    # version number is less than the current listed version.
    assert validate_version_number_is_gt_latest_signed_listed_version(
        addon, '122.9'
    ) == ('Version 122.9 must be greater than the previous approved version 123.0.')
    # version number is greater, so no error message.
    assert not validate_version_number_is_gt_latest_signed_listed_version(
        addon, '123.1'
    )

    addon.current_version.file.update(is_signed=False)
    # Same as current but check only applies to signed versions, so no error message.
    assert not validate_version_number_is_gt_latest_signed_listed_version(addon, '123')

    # Set up the scenario when a newer version has been signed, but then disabled
    addon.current_version.file.update(is_signed=True)
    disabled = version_factory(
        addon=addon,
        version='123.5',
        file_kw={'is_signed': True, 'status': amo.STATUS_DISABLED},
    )
    addon.reload()
    assert validate_version_number_is_gt_latest_signed_listed_version(
        addon, '123.1'
    ) == ('Version 123.1 must be greater than the previous approved version 123.5.')

    disabled.delete()
    # Shouldn't make a difference even if it's deleted - it was still signed.
    assert validate_version_number_is_gt_latest_signed_listed_version(
        addon, '123.1'
    ) == ('Version 123.1 must be greater than the previous approved version 123.5.')

    # Also check the edge case when addon is None
    assert not validate_version_number_is_gt_latest_signed_listed_version(None, '123')


@pytest.mark.django_db
def test_validate_version_number_is_gt_latest_signed_listed_version_not_langpack():
    addon = addon_factory(version_kw={'version': '123.0'}, file_kw={'is_signed': True})
    assert validate_version_number_is_gt_latest_signed_listed_version(addon, '122') == (
        'Version 122 must be greater than the previous approved version 123.0.'
    )
    addon.update(type=amo.ADDON_LPAPP)
    assert not validate_version_number_is_gt_latest_signed_listed_version(addon, '122')
