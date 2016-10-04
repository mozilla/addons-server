import pytest

from django.conf import settings
from django.core.management import call_command
from django.core.files.storage import default_storage as storage

from olympia import amo
from olympia.addons.management.commands import approve_addons
from olympia.addons.models import AddonFeatureCompatibility
from olympia.amo.tests import addon_factory, AMOPaths
from olympia.devhub.models import AddonLog
from olympia.editors.models import ReviewerScore


# Where to monkeypatch "lib.crypto.tasks.sign_addons" so it's correctly mocked.
SIGN_ADDONS = 'olympia.addons.management.commands.sign_addons.sign_addons'


# Test the "sign_addons" command.

def test_no_overridden_settings(monkeypatch):
    assert not settings.SIGNING_SERVER

    def no_endpoint(ids, **kwargs):
        assert not settings.SIGNING_SERVER

    monkeypatch.setattr(SIGN_ADDONS, no_endpoint)
    call_command('sign_addons', 123)


def test_override_SIGNING_SERVER_setting(monkeypatch):
    """You can override the SIGNING_SERVER settings."""
    assert not settings.SIGNING_SERVER

    def signing_server(ids, **kwargs):
        assert settings.SIGNING_SERVER == 'http://example.com'

    monkeypatch.setattr(SIGN_ADDONS, signing_server)
    call_command('sign_addons', 123, signing_server='http://example.com')


def test_force_signing(monkeypatch):
    """You can force signing an addon even if it's already signed."""
    def not_forced(ids, force, reason):
        assert not force
    monkeypatch.setattr(SIGN_ADDONS, not_forced)
    call_command('sign_addons', 123)

    def is_forced(ids, force, reason):
        assert force
    monkeypatch.setattr(SIGN_ADDONS, is_forced)
    call_command('sign_addons', 123, force=True)


def test_reason(monkeypatch):
    """You can pass a reason."""
    def has_reason(ids, force, reason):
        assert reason == 'expiry'
    monkeypatch.setattr(SIGN_ADDONS, has_reason)
    call_command('sign_addons', 123, reason='expiry')

# Test the "approve_addons" command.


@pytest.mark.django_db
def test_approve_addons_get_files_incomplete():
    """An incomplete add-on can't be approved."""
    addon = addon_factory(status=amo.STATUS_NULL)
    assert approve_addons.get_files([addon.guid]) == []


@pytest.mark.django_db
def test_approve_addons_get_files_bad_guid():
    """An add-on with another guid doesn't get approved."""
    addon1 = addon_factory(status=amo.STATUS_NOMINATED, guid='foo')
    addon1_file = addon1.latest_version.files.get()
    addon1_file.update(status=amo.STATUS_AWAITING_REVIEW)
    # Create another add-on that we won't get the files for.
    addon2 = addon_factory(status=amo.STATUS_NOMINATED, guid='bar')
    addon2_file = addon2.latest_version.files.get()
    addon2_file.update(status=amo.STATUS_AWAITING_REVIEW)
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
    params=[(amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW, 'full'),
            (amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW, 'full')],
    # ids are used to build better names for the tests using this fixture.
    ids=id_function)
def use_case(request, db):
    """This fixture will return quadruples for different use cases.

    Addon                   | File1 and 2        | Review type
    ==============================================================
    awaiting review         | awaiting review    | approved
    approved                | awaiting review    | approved
    """
    addon_status, file_status, review_type = request.param

    addon = addon_factory(status=addon_status, guid='foo')
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
    addon = addon_factory(status=amo.STATUS_PUBLIC)
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
    assert file1.reload().status == amo.STATUS_PUBLIC
    assert file2.reload().status == amo.STATUS_PUBLIC
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
    addon = addon_factory(status=amo.STATUS_PUBLIC)
    file_ = addon.versions.get().files.get()
    file_.update(status=amo.STATUS_PUBLIC)
    assert approve_addons.get_review_type(file_) is None


def test_approve_addons_get_review_type(use_case):
    """Review type depends on the file and addon status.

    Use cases are quadruples taken from the "use_case" fixture above.
    """
    addon, file1, _, review_type = use_case
    assert approve_addons.get_review_type(file1) == review_type


@pytest.mark.django_db
def test_populate_e10s_feature_compatibility():
    # Create addons...
    # One must have no latest file object.
    addon_unreviewed = addon_factory(
        name='no current version', status=amo.STATUS_NOMINATED)
    addon_unreviewed.update(_current_version=None)
    assert addon_unreviewed.get_latest_file() is None

    # One must have a latest file object with no file on the filesystem.
    addon_no_file = addon_factory(name='no file')
    assert not storage.exists(addon_no_file.get_latest_file().file_path)

    # One must have a file, and be e10s incompatible
    addon = addon_factory(guid='guid@xpi', name='not e10s compatible')
    AMOPaths().xpi_copy_over(addon.get_latest_file(), 'extension.xpi')
    assert storage.exists(addon.get_latest_file().file_path)

    # One must have a file, and be e10s compatible
    addon_compatible = addon_factory(
        guid='guid-e10s@xpi', name='e10s compatible')
    AMOPaths().xpi_copy_over(
        addon_compatible.get_latest_file(), 'extension_e10s.xpi')
    assert storage.exists(addon_compatible.get_latest_file().file_path)

    # One must have a file, and be a web extension
    addon_webextension = addon_factory(
        guid='@webextension-guid', name='web extension')
    AMOPaths().xpi_copy_over(
        addon_webextension.get_latest_file(), 'webextension.xpi')
    assert storage.exists(addon_webextension.get_latest_file().file_path)

    # One must be unlisted, and compatible.
    addon_compatible_unlisted = addon_factory(
        guid='unlisted-guid-e10s@xpi', name='unlisted e10s compatible webext',
        is_listed=False)
    AMOPaths().xpi_copy_over(
        addon_compatible_unlisted.get_latest_file(), 'webextension_no_id.xpi')
    assert storage.exists(
        addon_compatible_unlisted.get_latest_file().file_path)

    # Call the command !
    call_command('process_addons', task='populate_e10s_feature_compatibility')

    assert AddonFeatureCompatibility.objects.count() == 3

    addon.reload()
    assert addon.feature_compatibility.pk
    assert addon.feature_compatibility.e10s == amo.E10S_UNKNOWN

    addon_compatible.reload()
    assert addon_compatible.feature_compatibility.pk
    assert addon_compatible.feature_compatibility.e10s == amo.E10S_COMPATIBLE

    addon_webextension.reload()
    assert addon_webextension.feature_compatibility.pk
    assert (addon_webextension.feature_compatibility.e10s ==
            amo.E10S_COMPATIBLE_WEBEXTENSION)


@pytest.mark.django_db
def test_populate_e10s_feature_compatibility_with_unlisted():
    addon_compatible_unlisted = addon_factory(
        guid='unlisted-guid-e10s@xpi', name='unlisted e10s compatible webext',
        is_listed=False)
    AMOPaths().xpi_copy_over(
        addon_compatible_unlisted.get_latest_file(), 'webextension_no_id.xpi')
    assert storage.exists(
        addon_compatible_unlisted.get_latest_file().file_path)

    call_command('process_addons', task='populate_e10s_feature_compatibility',
                 with_unlisted=True)

    assert AddonFeatureCompatibility.objects.count() == 1

    addon_compatible_unlisted.reload()
    assert addon_compatible_unlisted.feature_compatibility.pk
    assert (addon_compatible_unlisted.feature_compatibility.e10s ==
            amo.E10S_COMPATIBLE_WEBEXTENSION)
