"""Real life review scenarios.

For different add-on and file statuses, test reviewing them, and make sure then
end up in the correct state.
"""
import pytest

from olympia import amo
from olympia.addons.models import Addon
from olympia.editors import helpers
from olympia.files.models import File
from olympia.versions.models import Version


@pytest.fixture
def mock_request(rf, db):  # rf is a RequestFactory provided by pytest-django.
    request = rf.get('/')
    request.user = amo.tests.user_factory()
    return request


@pytest.fixture
def addon_with_files(db):
    """Return an add-on with one version and four files.

    By default the add-on is public, and the files are: beta, disabled,
    unreviewed, unreviewed.
    """
    addon = Addon.objects.create()
    version = Version.objects.create(addon=addon)
    for status in [amo.STATUS_BETA, amo.STATUS_DISABLED, amo.STATUS_UNREVIEWED,
                   amo.STATUS_UNREVIEWED]:
        File.objects.create(version=version, status=status)
    return addon


@pytest.mark.parametrize(
    'review_action,addon_status,file_status,review_class,review_type,'
    'final_addon_status,final_file_status',
    [
        # New addon request full.
        # scenario0: should succeed, files approved.
        ('process_public', amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
         helpers.ReviewAddon, 'nominated', amo.STATUS_PUBLIC,
         amo.STATUS_PUBLIC),
        # scenario1: should succeed, files rejected.
        ('process_sandbox', amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
         helpers.ReviewAddon, 'nominated', amo.STATUS_NULL,
         amo.STATUS_DISABLED),
        # scenario2: should succeed, files approved.
        ('process_preliminary', amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
         helpers.ReviewAddon, 'nominated', amo.STATUS_LITE, amo.STATUS_LITE),

        # New addon request prelim.
        # scenario3: should fail, no change.
        ('process_public', amo.STATUS_UNREVIEWED, amo.STATUS_UNREVIEWED,
         helpers.ReviewAddon, 'preliminary', amo.STATUS_UNREVIEWED,
         amo.STATUS_UNREVIEWED),
        # scenario4: Should succeed, files rejected.
        ('process_sandbox', amo.STATUS_UNREVIEWED, amo.STATUS_UNREVIEWED,
         helpers.ReviewAddon, 'preliminary', amo.STATUS_NULL,
         amo.STATUS_DISABLED),
        # scenario5: should succeed, files approved.
        ('process_preliminary', amo.STATUS_UNREVIEWED, amo.STATUS_UNREVIEWED,
         helpers.ReviewAddon, 'preliminary', amo.STATUS_LITE, amo.STATUS_LITE),

        # Prelim addon request full.
        # scenario6: should succeed, files approved.
        ('process_public', amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_LITE,
         helpers.ReviewAddon, 'nominated', amo.STATUS_PUBLIC,
         amo.STATUS_PUBLIC),
        # scenario7: should succeed, files rejected.
        ('process_sandbox', amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_LITE,
         helpers.ReviewAddon, 'nominated', amo.STATUS_NULL,
         amo.STATUS_DISABLED),
        # scenario8: Should succeed, files approved.
        ('process_preliminary', amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_LITE,
         helpers.ReviewAddon, 'nominated', amo.STATUS_LITE, amo.STATUS_LITE),

        # Full addon with a new file.
        # scenario9: should succeed, files approved.
        ('process_public', amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED,
         helpers.ReviewFiles, 'pending', amo.STATUS_PUBLIC, amo.STATUS_PUBLIC),
        # scenario10: should succeed, files rejected.
        ('process_sandbox', amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED,
         helpers.ReviewFiles, 'pending', amo.STATUS_UNREVIEWED,
         amo.STATUS_DISABLED),
        # scenario11: should succeed, files approved.
        ('process_preliminary', amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED,
         helpers.ReviewFiles, 'pending', amo.STATUS_LITE, amo.STATUS_LITE),

        # Prelim addon with a new file.
        # scenario12: should fail, no change.
        ('process_public', amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
         helpers.ReviewFiles, 'preliminary', amo.STATUS_LITE,
         amo.STATUS_UNREVIEWED),
        # scenario13: should succeed, files rejected.
        ('process_sandbox', amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
         helpers.ReviewFiles, 'preliminary', amo.STATUS_LITE,
         amo.STATUS_DISABLED),
        # scenario14: should succeed, files approved.
        ('process_preliminary', amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
         helpers.ReviewFiles, 'preliminary', amo.STATUS_LITE, amo.STATUS_LITE),
    ])
def test_review_scenario(mock_request, addon_with_files, review_action,
                         addon_status, file_status, review_class, review_type,
                         final_addon_status, final_file_status):
    # Setup the addon and files.
    addon = addon_with_files
    addon.update(status=addon_status)
    version = addon.versions.get()
    version.files.filter(status=amo.STATUS_NULL).update(status=file_status)
    # Get the review helper.
    helper = helpers.ReviewHelper(mock_request, addon, version)
    assert isinstance(helper.handler, review_class)
    helper.get_review_type(mock_request, addon, version)
    assert helper.review_type == review_type
    helper.set_data({'comments': 'testing review scenarios'})
    # Run the action (process_public, process_sandbox, process_preliminary).
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
        [amo.STATUS_BETA, amo.STATUS_DISABLED, final_file_status,
         final_file_status])
