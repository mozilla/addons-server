import pytest
import StringIO
from datetime import datetime, timedelta
import mock

from django.conf import settings
from django.core.management import call_command
from django.core.files.storage import default_storage as storage

from olympia import amo
from olympia.addons.management.commands import approve_addons
from olympia.addons.models import AddonFeatureCompatibility
from olympia.addons.tasks import migrate_preliminary_to_full
from olympia.amo.tests import addon_factory, AMOPaths, version_factory
from olympia.devhub.models import AddonLog
from olympia.editors.models import ReviewerScore
from olympia.versions.models import Version


# Where to monkeypatch "lib.crypto.tasks.sign_addons" so it's correctly mocked.
SIGN_ADDONS = 'olympia.addons.management.commands.sign_addons.sign_addons'


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
    addon1 = addon_factory(status=amo.STATUS_UNREVIEWED, guid='foo')
    addon1_file = addon1.latest_version.files.get()
    addon1_file.update(status=amo.STATUS_UNREVIEWED)
    # Create another add-on that we won't get the files for.
    addon2 = addon_factory(status=amo.STATUS_UNREVIEWED, guid='bar')
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
    params=[(amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED, 'full'),
            (amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED, 'full')],
    # ids are used to build better names for the tests using this fixture.
    ids=id_function)
def use_case(request, db):
    """This fixture will return quadruples for different use cases.

    Addon                   | File1 and 2        | Review type
    ==============================================================
    waiting for full        | unreviewed         | fully reviewed
    fully reviewed          | unreviewed         | fully reviewed
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
        name='no current version', status=amo.STATUS_UNREVIEWED)
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


@pytest.mark.django_db
@mock.patch('olympia.addons.tasks.log')
@pytest.mark.parametrize(
    'pre_addon_status, pre_file1_status, pre_file3_status, enabled, listed, '
    'end_addon_status, end_file1_status, end_file3_status, end_experimental, '
    'added_note, send_email',
    [(amo.STATUS_LITE, amo.STATUS_LITE, amo.STATUS_LITE, True, True,
      amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, True,
      True, True),

     (amo.STATUS_LITE, amo.STATUS_LITE, amo.STATUS_LITE, False, True,
      amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, True,
      True, False),

     (amo.STATUS_LITE, amo.STATUS_LITE, amo.STATUS_LITE, True, False,
      amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, True,
      True, False),

     (amo.STATUS_UNREVIEWED, amo.STATUS_DISABLED, amo.STATUS_UNREVIEWED, True,
      True,
      amo.STATUS_NOMINATED, amo.STATUS_DISABLED, amo.STATUS_UNREVIEWED, True,
      True, True),

     (amo.STATUS_UNREVIEWED, amo.STATUS_DISABLED, amo.STATUS_UNREVIEWED, False,
      True,
      amo.STATUS_NOMINATED, amo.STATUS_DISABLED, amo.STATUS_UNREVIEWED, True,
      True, False),

     (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_LITE, amo.STATUS_LITE, True,
      True,
      amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, False,
      True, True),

     (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
      True, True,
      amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED, False,
      True, True),

     (amo.STATUS_PUBLIC, amo.STATUS_LITE, amo.STATUS_PUBLIC, True, True,
      amo.STATUS_PUBLIC, amo.STATUS_DISABLED, amo.STATUS_PUBLIC, False,
      False, False)])
def test_migrate_preliminary(
        logger_mock,
        pre_addon_status, pre_file1_status, pre_file3_status, enabled, listed,
        end_addon_status, end_file1_status, end_file3_status, end_experimental,
        added_note, send_email, mozilla_user):
    """Addons and versions are migrated correctly."""
    an_hour_ago = datetime.now() - timedelta(hours=1)
    addon = addon_factory(status=pre_addon_status, is_listed=listed,
                          version_kw={'version': '1', 'created': an_hour_ago},
                          file_kw={'status': pre_file1_status})
    # Add a disabled version to test original_status
    version_factory(addon=addon, version='2', file_kw={
        'status': amo.STATUS_DISABLED, 'original_status': amo.STATUS_LITE})
    version = version_factory(addon=addon, version='3',
                              file_kw={'status': pre_file3_status})
    addon.update(status=pre_addon_status, disabled_by_user=(not enabled))
    addon.reload()
    assert addon.latest_version == version
    assert addon.status == pre_addon_status
    assert addon.is_experimental is False

    output = StringIO.StringIO()
    migrate_preliminary_to_full([addon.id], out=output)
    addon.reload()
    assert addon.status == end_addon_status
    assert addon.is_experimental == end_experimental
    # Check v1's status matches
    v1 = Version.objects.filter(addon=addon, version='1')[0]
    assert v1.all_files[0].status == end_file1_status
    # Now check original_status worked too
    v2 = Version.objects.filter(addon=addon, version='2')[0]
    if pre_addon_status in [amo.STATUS_UNREVIEWED, amo.STATUS_PUBLIC]:
        assert v2.all_files[0].original_status == amo.STATUS_DISABLED
    else:
        assert v2.all_files[0].original_status == amo.STATUS_PUBLIC
    # Lastly check the latest version, v3
    assert addon.latest_version.all_files[0].status == end_file3_status
    assert addon.disabled_by_user == (not enabled)
    if added_note:
        logs = AddonLog.objects.filter(
            addon=addon,
            activity_log__action=amo.LOG.PRELIMINARY_ADDON_MIGRATED.id)
        assert len(logs) == 1
        assert logs[0].activity_log.details['email'] == send_email
    if send_email:
        log_string = 'Add-ons that need to be email notified: [%s]' % addon.id
        logger_mock.info.assert_called_with(log_string)
