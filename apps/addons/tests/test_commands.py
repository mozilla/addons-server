import mock
import pytest

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

import amo
import amo.tests
from addons.management.commands import approve_addons
from devhub.models import AddonLog
from editors.models import ReviewerScore


# Where to monkeypatch "lib.crypto.tasks.sign_addons" so it's correctly mocked.
SIGN_ADDONS = 'addons.management.commands.sign_addons.sign_addons'


# Test the "sign_addons" command.

def test_no_overridden_settings(monkeypatch):
    assert not settings.SIGNING_SERVER
    assert not settings.PRELIMINARY_SIGNING_SERVER

    def no_endpoint(ids, **kwargs):
        assert not settings.SIGNING_SERVER
        assert not settings.PRELIMINARY_SIGNING_SERVER

    monkeypatch.setattr(SIGN_ADDONS, no_endpoint)
    call_command('sign_addons', 123)


def test_override_SIGNING_SERVER_setting(monkeypatch):
    """You can override the SIGNING_SERVER settings."""
    assert not settings.SIGNING_SERVER

    def signing_server(ids, **kwargs):
        assert settings.SIGNING_SERVER == 'http://example.com'

    monkeypatch.setattr(SIGN_ADDONS, signing_server)
    call_command('sign_addons', 123, signing_server='http://example.com')


def test_override_PRELIMINARY_SIGNING_SERVER_setting(monkeypatch):
    """You can override the PRELIMINARY_SIGNING_SERVER settings."""
    assert not settings.PRELIMINARY_SIGNING_SERVER

    def preliminary_signing_server(ids, **kwargs):
        assert settings.PRELIMINARY_SIGNING_SERVER == 'http://example.com'

    monkeypatch.setattr(SIGN_ADDONS, preliminary_signing_server)
    call_command('sign_addons', 123,
                 preliminary_signing_server='http://example.com')


def test_force_signing(monkeypatch):
    """You can force signing an addon even if it's already signed."""
    def not_forced(ids, force):
        assert not force
    monkeypatch.setattr(SIGN_ADDONS, not_forced)
    call_command('sign_addons', 123)

    def is_forced(ids, force):
        assert force
    monkeypatch.setattr(SIGN_ADDONS, is_forced)
    call_command('sign_addons', 123, force=True)


# Test the "approve_addons" command.

@pytest.mark.django_db
def test_approve_addons_get_files_incomplete():
    """An incomplete add-on can't be approved."""
    addon = amo.tests.addon_factory(status=amo.STATUS_NULL)
    assert approve_addons.get_files([addon.guid]) == []


@pytest.mark.django_db
def test_approve_addons_get_files_bad_guid():
    """An add-on with another guid doesn't get approved."""
    addon1 = amo.tests.addon_factory(status=amo.STATUS_UNREVIEWED, guid='foo')
    addon1_file = addon1.latest_version.files.get()
    addon1_file.update(status=amo.STATUS_UNREVIEWED)
    # Create another add-on that we won't get the files for.
    addon2 = amo.tests.addon_factory(status=amo.STATUS_UNREVIEWED, guid='bar')
    addon2_file = addon2.latest_version.files.get()
    addon2_file.update(status=amo.STATUS_UNREVIEWED)
    # There's only the addon1's file returned, no other.
    assert approve_addons.get_files(['foo']) == [addon1_file]


def id_function(fixture_value):
    """Convert a param from the use_case fixture to a nicer name.

    By default, the name (used in the test generated from the parameterized
    fixture) will use the fixture name and a number.
    Eg: test_foo[use_case0]

    Providing explicit 'ids' (either as strings, or as a function) will use
    those names instead. Here the name will be something like
    test_foo[public-unreviewed-full], for the status values, and if the file is
    unreviewed.
    """
    addon_status, file_status, review_type = fixture_value
    return '{0}-{1}-{2}'.format(amo.STATUS_CHOICES_API[addon_status],
                                amo.STATUS_CHOICES_API[file_status],
                                review_type)


@pytest.fixture(
    params=[(amo.STATUS_UNREVIEWED, amo.STATUS_UNREVIEWED, 'prelim'),
            (amo.STATUS_LITE, amo.STATUS_UNREVIEWED, 'prelim'),
            (amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED, 'full'),
            (amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED, 'full'),
            (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_LITE, 'full')],
    # ids are used to build better names for the tests using this fixture.
    ids=id_function)
def use_case(request, db):
    """This fixture will return quadruples for different use cases.

    Addon                   | File1 and 2        | Review type
    ==============================================================
    waiting for prelim      | unreviewed         | prelim reviewed
    prelim reviewed         | unreviewed         | prelim reviewed
    waiting for full        | unreviewed         | fully reviewed
    fully reviewed          | unreviewed         | fully reviewed
    prelim waiting for full | prelim reviewed    | fully reviewed
    """
    addon_status, file_status, review_type = request.param

    addon = amo.tests.addon_factory(status=addon_status, guid='foo')
    version = addon.latest_version
    file1 = version.files.get()
    file1.update(status=file_status)
    # A second file for good measure.
    file2 = amo.tests.file_factory(version=version, status=file_status)
    # If the addon is public, and we change its only file to something else
    # than public, it'll change to unreviewed.
    addon.update(status=addon_status)
    assert addon.reload().status == addon_status
    assert file1.reload().status == file_status
    assert file2.reload().status == file_status

    return (addon, file1, file2, review_type)


@pytest.fixture
def mozilla_user(db):
    """Create and return the "mozilla" user used to auto approve addons."""
    return amo.tests.user_factory(id=settings.TASK_USER_ID)


def test_approve_addons_get_files(use_case):
    """Files that need to get approved are returned in the list.

    Use cases are quadruples taken from the "use_case" fixture above.
    """
    addon, file1, file2, review_type = use_case
    assert approve_addons.get_files([addon.guid]) == [file1, file2]


@pytest.mark.django_db
def test_approve_addons_approve_files_no_review_type():
    """Files which don't need approval don't change status."""
    # Create the "mozilla" user, needed for the log.
    amo.tests.user_factory(id=settings.TASK_USER_ID)
    addon = amo.tests.addon_factory(status=amo.STATUS_PUBLIC)
    file_ = addon.versions.get().files.get()
    file_.update(status=amo.STATUS_PUBLIC)
    approve_addons.approve_files([(file_, None)])
    # Nothing changed.
    assert addon.reload().status == amo.STATUS_PUBLIC
    assert file_.reload().status == amo.STATUS_PUBLIC


def test_approve_addons_approve_files(use_case, mozilla_user):
    """Files are approved using the correct review type.

    Use cases are quadruples taken from the "use_case" fixture above.
    """
    addon, file1, file2, review_type = use_case
    approve_addons.approve_files([(file1, review_type),
                                  (file2, review_type)])
    assert file1.reload().status == (
        amo.STATUS_LITE if review_type == 'prelim' else amo.STATUS_PUBLIC)
    assert file2.reload().status == (
        amo.STATUS_LITE if review_type == 'prelim' else amo.STATUS_PUBLIC)
    logs = AddonLog.objects.filter(addon=addon)
    assert len(logs) == 2  # One per file.
    file1_log, file2_log = logs
    # An AddonLog has been created for each approval.
    assert file1_log.activity_log.details['comments'] == u'bulk approval'
    assert file1_log.activity_log.user == mozilla_user
    assert file2_log.activity_log.details['comments'] == u'bulk approval'
    assert file2_log.activity_log.user == mozilla_user
    # No ReviewerScore was granted, it's an automatic approval.
    assert not ReviewerScore.objects.all()


@pytest.mark.django_db
def test_approve_addons_get_review_type_already_approved():
    """The review type for a file that doesn't need approval is None."""
    addon = amo.tests.addon_factory(status=amo.STATUS_PUBLIC)
    file_ = addon.versions.get().files.get()
    file_.update(status=amo.STATUS_PUBLIC)
    assert approve_addons.get_review_type(file_) is None


def test_approve_addons_get_review_type(use_case):
    """Review type depends on the file and addon status.

    Use cases are quadruples taken from the "use_case" fixture above.
    """
    addon, file1, _, review_type = use_case
    assert approve_addons.get_review_type(file1) == review_type


# fix_let_scope_bustage.


def test_fix_let_scope_bustage_no_addon_id():
    """If no add-on id is provided, raise."""
    with pytest.raises(CommandError) as exc_info:
        call_command('fix_let_scope_bustage')
    assert 'Please provide at least one add-on id to fix.' in exc_info.value


@mock.patch('addons.management.commands.fix_let_scope_bustage.'
            'fix_let_scope_bustage_in_addons.delay')
def test_fix_let_scope_bustage(mock_fixer):
    """The command should call the task with the list of add-on id provided."""
    call_command('fix_let_scope_bustage', 1, 2, 3)
    mock_fixer.assert_called_once_with([1, 2, 3])
