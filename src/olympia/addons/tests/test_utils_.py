from datetime import datetime, timedelta
from unittest import mock

from django.forms import ValidationError

import pytest
import time_machine
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import AddonApprovalsCounter
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.users.models import Group, GroupUser

from ..utils import (
    RECOMMENDATIONS,
    DeleteTokenSigner,
    get_addon_recommendations,
    get_filtered_fallbacks,
    request_content_review,
    trigger_content_review,
    validate_addon_name,
    validate_addon_summary,
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
    validate_addon_name(name, user=user)


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
        'ꮇozi𝈪𝈪a',
        'Moziꙇꙇa',
        'Firefox awesome for Mozilla',
        'Firefox awesome for Mozilla',
        'ƒireføx',
        'ϝirefox',
        'FIRꭼfox',
        '𝈓ꞁR⋿FOX',
        'flref0x',
    ),
)
def test_validate_addon_name_disallowed_without_permission(name):
    normal_user = user_factory()
    special_user = user_factory()
    group = Group.objects.create(name=name, rules='Trademark:Bypass')
    GroupUser.objects.create(group=group, user=special_user)

    # Validates with the permission.
    validate_addon_name(name, user=special_user)

    # Raises an error without.
    with pytest.raises(ValidationError) as exc:
        validate_addon_name(name, user=normal_user)
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
    group = Group.objects.create(rules='Trademark:Bypass')
    GroupUser.objects.create(group=group, user=special_user)

    # Raises an error without the permission...
    with pytest.raises(ValidationError) as exc:
        validate_addon_name(name, user=normal_user)
    assert exc.value.message == 'This name cannot be used.'

    # ... and also with it.
    with pytest.raises(ValidationError) as exc2:
        validate_addon_name(name, user=special_user)
    assert exc2.value.message == 'This name cannot be used.'


@pytest.mark.django_db
@pytest.mark.parametrize(
    'summary',
    (
        'I' * 17,  # Too many homoglyphs
        'I' * 50,  # Way too many homoglyphs!
    ),
)
def test_validate_addon_summary_disallowed_no_matter_what(summary):
    normal_user = user_factory()
    special_user = user_factory()
    group = Group.objects.create(rules='Trademark:Bypass')
    GroupUser.objects.create(group=group, user=special_user)

    # Raises an error without the permission...
    with pytest.raises(ValidationError) as exc:
        validate_addon_summary(summary, user=normal_user)
    assert exc.value.message == 'This add-on summary or description cannot be used.'

    # ... and also with it.
    with pytest.raises(ValidationError) as exc2:
        validate_addon_summary(summary, user=special_user)
    assert exc2.value.message == 'This add-on summary or description cannot be used.'


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


def test_delete_token_signer():
    signer = DeleteTokenSigner()
    addon_id = 1234
    with time_machine.travel(datetime.now(), tick=False) as frozen_time:
        token = signer.generate(addon_id)
        # generated token is valid
        assert signer.validate(token, addon_id)
        # generating with the same addon_id at the same time returns the same value
        assert token == signer.generate(addon_id)
        # generating with a different addon_id at the same time returns different value
        assert token != signer.generate(addon_id + 1)
        # and the addon_id must match for it to be a valid token
        assert not signer.validate(token, addon_id + 1)

        # token is valid for 60 seconds so after 59 is still valid
        frozen_time.shift(timedelta(seconds=59))
        assert signer.validate(token, addon_id)

        # but not after 60 seconds
        frozen_time.shift(timedelta(seconds=2))
        assert not signer.validate(token, addon_id)


@pytest.mark.django_db
def test_trigger_content_review():
    addon = addon_factory(status=amo.STATUS_REJECTED)
    activity_log = ActivityLog.objects.create(
        amo.LOG.EDIT_ADDON_PROPERTY, user=user_factory()
    )
    AddonApprovalsCounter.approve_content_for_addon(addon)
    assert (
        addon.addonapprovalscounter.content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.PASS
    )

    with (
        override_switch('content-review-in-cinder', active=True),
        mock.patch('olympia.amo.celery.AMOTask.apply_async') as mock_apply_async,
    ):
        trigger_content_review(addon, activity_log)

    assert (
        addon.addonapprovalscounter.reload().content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.CHANGED
    )
    # And we should have triggered the content review task
    mock_apply_async.assert_called_once()
    assert mock_apply_async.call_args.args == ((), {'activity_log_pk': activity_log.pk})


@pytest.mark.django_db
def test_trigger_content_review_not_triggered_for_non_content_review_types():
    addon = addon_factory(type=amo.ADDON_STATICTHEME, status=amo.STATUS_REJECTED)
    activity_log = ActivityLog.objects.create(
        amo.LOG.EDIT_ADDON_PROPERTY, user=user_factory()
    )
    AddonApprovalsCounter.approve_content_for_addon(addon)
    assert (
        addon.addonapprovalscounter.content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.PASS
    )

    with (
        override_switch('content-review-in-cinder', active=True),
        mock.patch('olympia.amo.celery.AMOTask.apply_async') as mock_apply_async,
    ):
        trigger_content_review(addon, activity_log)

    assert (
        addon.addonapprovalscounter.reload().content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.CHANGED
    )
    # We should not have triggered the content review task though
    mock_apply_async.assert_not_called()


@pytest.mark.django_db
def test_trigger_content_review_not_triggered_if_switch_inactive():
    addon = addon_factory(status=amo.STATUS_REJECTED)
    activity_log = ActivityLog.objects.create(
        amo.LOG.EDIT_ADDON_PROPERTY, user=user_factory()
    )
    AddonApprovalsCounter.approve_content_for_addon(addon)
    assert (
        addon.addonapprovalscounter.content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.PASS
    )

    with (
        override_switch('content-review-in-cinder', active=False),
        mock.patch('olympia.amo.celery.AMOTask.apply_async') as mock_apply_async,
    ):
        trigger_content_review(addon, activity_log)

    assert (
        addon.addonapprovalscounter.reload().content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.CHANGED
    )
    # We should not have triggered the content review task though
    mock_apply_async.assert_not_called()


@pytest.mark.django_db
def test_request_content_review():
    addon = addon_factory(status=amo.STATUS_REJECTED)
    activity_log = ActivityLog.objects.create(
        amo.LOG.EDIT_ADDON_PROPERTY, user=user_factory()
    )
    AddonApprovalsCounter.reject_content_for_addon(addon)
    assert (
        addon.addonapprovalscounter.content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL
    )

    with (
        override_switch('content-review-in-cinder', active=True),
        mock.patch('olympia.amo.celery.AMOTask.apply_async') as mock_apply_async,
    ):
        request_content_review(addon, activity_log)

    assert (
        addon.addonapprovalscounter.reload().content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.REQUESTED
    )
    # And we should have triggered the content review task
    mock_apply_async.assert_called_once()
    assert mock_apply_async.call_args.args == ((), {'activity_log_pk': activity_log.pk})


@pytest.mark.django_db
def test_request_content_review_not_triggered_for_non_content_review_types():
    addon = addon_factory(type=amo.ADDON_STATICTHEME, status=amo.STATUS_REJECTED)
    activity_log = ActivityLog.objects.create(
        amo.LOG.EDIT_ADDON_PROPERTY, user=user_factory()
    )
    AddonApprovalsCounter.reject_content_for_addon(addon)
    assert (
        addon.addonapprovalscounter.content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL
    )

    with (
        override_switch('content-review-in-cinder', active=True),
        mock.patch('olympia.amo.celery.AMOTask.apply_async') as mock_apply_async,
    ):
        request_content_review(addon, activity_log)

    assert (
        addon.addonapprovalscounter.reload().content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.REQUESTED
    )
    # We should not have triggered the content review task though
    mock_apply_async.assert_not_called()


@pytest.mark.django_db
def test_request_content_review_not_triggered_if_switch_inactive():
    addon = addon_factory(status=amo.STATUS_REJECTED)
    activity_log = ActivityLog.objects.create(
        amo.LOG.EDIT_ADDON_PROPERTY, user=user_factory()
    )
    AddonApprovalsCounter.reject_content_for_addon(addon)
    assert (
        addon.addonapprovalscounter.content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL
    )

    with (
        override_switch('content-review-in-cinder', active=False),
        mock.patch('olympia.amo.celery.AMOTask.apply_async') as mock_apply_async,
    ):
        request_content_review(addon, activity_log)

    assert (
        addon.addonapprovalscounter.reload().content_review_status
        == AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.REQUESTED
    )
    # We should not have triggered the content review task though
    mock_apply_async.assert_not_called()
