"""Real life review scenarios.

For different add-on and file statuses, test reviewing them, and make sure then
end up in the correct state.
"""
from unittest import mock
import pytest

from olympia import amo
from olympia.amo.tests import addon_factory, user_factory
from olympia.reviewers.utils import ReviewAddon, ReviewFiles, ReviewHelper


@pytest.fixture
def mock_request(rf, db):  # rf is a RequestFactory provided by pytest-django.
    request = rf.get('/')
    request.user = user_factory()
    return request


@mock.patch('olympia.reviewers.utils.sign_file', lambda f: None)
@pytest.mark.parametrize(
    'review_action,addon_status,file_status,review_class,review_type,'
    'final_addon_status,final_file_status',
    [
        # New addon request full.
        # scenario0: should succeed, files approved.
        (
            'approve_latest_version',
            amo.STATUS_NOMINATED,
            amo.STATUS_AWAITING_REVIEW,
            ReviewAddon,
            'extension_nominated',
            amo.STATUS_APPROVED,
            amo.STATUS_APPROVED,
        ),
        # scenario1: should succeed, files rejected.
        (
            'reject_latest_version',
            amo.STATUS_NOMINATED,
            amo.STATUS_AWAITING_REVIEW,
            ReviewAddon,
            'extension_nominated',
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
            'extension_pending',
            amo.STATUS_APPROVED,
            amo.STATUS_APPROVED,
        ),
        # scenario3: should succeed, files rejected.
        (
            'reject_latest_version',
            amo.STATUS_APPROVED,
            amo.STATUS_AWAITING_REVIEW,
            ReviewFiles,
            'extension_pending',
            amo.STATUS_NULL,
            amo.STATUS_DISABLED,
        ),
    ],
)
def test_review_scenario(
    mock_request,
    review_action,
    addon_status,
    file_status,
    review_class,
    review_type,
    final_addon_status,
    final_file_status,
):
    # Setup the addon and files.
    addon = addon_factory(
        name='My Addon',
        slug='my-addon',
        status=addon_status,
        file_kw={'status': file_status},
    )
    version = addon.versions.get()
    # Get the review helper.
    helper = ReviewHelper(mock_request, addon, version)
    assert isinstance(helper.handler, review_class)
    helper.set_review_handler(mock_request)
    assert helper.handler.review_type == review_type
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
