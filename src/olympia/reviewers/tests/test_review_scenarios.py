"""Real life review scenarios.

For different add-on and file statuses, test reviewing them, and make sure then
end up in the correct state.
"""
import pytest

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import user_factory
from olympia.files.models import File
from olympia.reviewers.utils import ReviewAddon, ReviewFiles, ReviewHelper
from olympia.versions.models import Version


@pytest.fixture
def mock_request(rf, db):  # rf is a RequestFactory provided by pytest-django.
    request = rf.get('/')
    request.user = user_factory()
    return request


@pytest.fixture
def addon_with_files(db):
    """Return an add-on with one version and three files.

    By default the add-on is public, and the files are: disabled,
    unreviewed, unreviewed.
    """
    addon = Addon.objects.create(name='My Addon', slug='my-addon')
    version = Version.objects.create(addon=addon)
    for status in [amo.STATUS_DISABLED,
                   amo.STATUS_AWAITING_REVIEW, amo.STATUS_AWAITING_REVIEW]:
        File.objects.create(version=version, status=status)
    return addon


@pytest.mark.parametrize(
    'review_action,addon_status,file_status,review_class,review_type,'
    'final_addon_status,final_file_status',
    [
        # New addon request full.
        # scenario0: should succeed, files approved.
        ('process_public', amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW,
         ReviewAddon, 'nominated', amo.STATUS_PUBLIC,
         amo.STATUS_PUBLIC),
        # scenario1: should succeed, files rejected.
        ('process_sandbox', amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW,
         ReviewAddon, 'nominated', amo.STATUS_NULL,
         amo.STATUS_DISABLED),

        # Approved addon with a new file.
        # scenario2: should succeed, files approved.
        ('process_public', amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW,
         ReviewFiles, 'pending', amo.STATUS_PUBLIC,
         amo.STATUS_PUBLIC),
        # scenario3: should succeed, files rejected.
        ('process_sandbox', amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW,
         ReviewFiles, 'pending', amo.STATUS_NULL,
         amo.STATUS_DISABLED),
    ])
def test_review_scenario(mock_request, addon_with_files, review_action,
                         addon_status, file_status, review_class, review_type,
                         final_addon_status, final_file_status):
    # Setup the addon and files.
    addon = addon_with_files
    addon.update(status=addon_status)
    version = addon.versions.get()
    version.files.filter(
        status=amo.STATUS_AWAITING_REVIEW).update(status=file_status)
    # Get the review helper.
    helper = ReviewHelper(mock_request, addon, version)
    assert isinstance(helper.handler, review_class)
    helper.set_review_handler(mock_request)
    assert helper.handler.review_type == review_type
    helper.set_data({'comments': 'testing review scenarios'})
    # Run the action (process_public, process_sandbox).
    try:
        getattr(helper.handler, review_action)()
    except AssertionError:
        # Some scenarios are expected to fail. We don't need to check it here,
        # the scenario has the final statuses, and those are the ones we want
        # to check.
        pass
    # Check the final statuses.
    assert addon.reload().status == final_addon_status
    assert list(version.files.values_list('status', flat=True)) == (
        [amo.STATUS_DISABLED, final_file_status, final_file_status])
