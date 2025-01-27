"""Real life review scenarios.

For different add-on and file statuses, test reviewing them, and make sure then
end up in the correct state.
"""

import json
import uuid
from unittest import mock

from django.conf import settings

import pytest
import responses

from olympia import amo
from olympia.amo.tests import addon_factory, user_factory
from olympia.reviewers.utils import ReviewAddon, ReviewFiles, ReviewHelper


@mock.patch('olympia.reviewers.utils.sign_file', lambda f: None)
@pytest.mark.django_db
@pytest.mark.parametrize(
    'review_action,addon_status,file_status,review_class,final_addon_status,final_file_status',
    [
        # New addon request full.
        # scenario0: should succeed, files approved.
        (
            'approve_latest_version',
            amo.STATUS_NOMINATED,
            amo.STATUS_AWAITING_REVIEW,
            ReviewAddon,
            amo.STATUS_APPROVED,
            amo.STATUS_APPROVED,
        ),
        # scenario1: should succeed, files rejected.
        (
            'reject_latest_version',
            amo.STATUS_NOMINATED,
            amo.STATUS_AWAITING_REVIEW,
            ReviewAddon,
            amo.STATUS_NULL,
            amo.STATUS_DISABLED,
        ),
        # Approved addon with a new file.
        # scenario2: should succeed, files approved.
        (
            'approve_latest_version',
            amo.STATUS_APPROVED,
            amo.STATUS_AWAITING_REVIEW,
            ReviewFiles,
            amo.STATUS_APPROVED,
            amo.STATUS_APPROVED,
        ),
        # scenario3: should succeed, files rejected.
        (
            'reject_latest_version',
            amo.STATUS_APPROVED,
            amo.STATUS_AWAITING_REVIEW,
            ReviewFiles,
            amo.STATUS_NULL,
            amo.STATUS_DISABLED,
        ),
    ],
)
def test_review_scenario(
    review_action,
    addon_status,
    file_status,
    review_class,
    final_addon_status,
    final_file_status,
):
    responses.add_callback(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_decision',
        callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
    )
    # Setup the addon and files.
    addon = addon_factory(
        name='My Addon',
        slug='my-addon',
        status=addon_status,
        file_kw={'status': file_status},
    )
    version = addon.versions.get()
    # Get the review helper.
    helper = ReviewHelper(addon=addon, version=version, user=user_factory())
    assert isinstance(helper.handler, review_class)
    helper.set_data({'comments': 'testing review scenarios'})
    # Run the action (approve_latest_version, reject_latest_version).
    try:
        getattr(helper.handler, review_action)()
    except AssertionError:
        # Some scenarios are expected to fail. We don't need to check it here,
        # the scenario has the final statuses, and those are the ones we want
        # to check.
        pass
    # Check the final statuses.
    assert addon.reload().status == final_addon_status
    assert version.file.reload().status == final_file_status
