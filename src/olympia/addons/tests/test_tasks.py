import mock
import os
import pytest
import tempfile
from datetime import datetime

from django.conf import settings
from django.core import mail
from django.test.utils import override_settings

from freezegun import freeze_time

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons import cron
from olympia.addons.models import Addon, AddonCategory, MigratedLWT
from olympia.addons.tasks import (
    add_static_theme_from_lwt, create_persona_preview_images,
    migrate_legacy_dictionary_to_webextension, migrate_lwts_to_static_themes,
    save_persona_image,
    migrate_webextensions_to_git_storage)
from olympia.amo.storage_utils import copy_stored_file
from olympia.amo.tests import (
    addon_factory, TestCase, user_factory, version_factory)
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import image_size
from olympia.applications.models import AppVersion
from olympia.constants import licenses
from olympia.constants.categories import CATEGORIES
from olympia.files.models import FileUpload
from olympia.files.utils import id_to_path
from olympia.ratings.models import Rating
from olympia.stats.models import ThemeUpdateCount, UpdateCount
from olympia.tags.models import Tag
from olympia.users.models import UserProfile
from olympia.versions.models import License
from olympia.lib.git import AddonGitRepository


class TestPersonaImageFunctions(TestCase):
    @mock.patch('olympia.addons.tasks.pngcrush_image')
    def test_create_persona_preview_image(self, pngcrush_image_mock):
        addon = addon_factory()
        addon.modified = self.days_ago(41)
        # Given an image, a 680x100 and a 32x32 thumbnails need to be generated
        # and processed with pngcrush.
        expected_dst1 = tempfile.NamedTemporaryFile(
            mode='r+w+b', suffix=".png", delete=False, dir=settings.TMP_PATH)
        expected_dst2 = tempfile.NamedTemporaryFile(
            mode='r+w+b', suffix=".png", delete=False, dir=settings.TMP_PATH)
        create_persona_preview_images(
            src=get_image_path('persona-header.jpg'),
            full_dst=[expected_dst1.name, expected_dst2.name],
            set_modified_on=addon.serializable_reference(),
        )
        # pngcrush_image should have been called twice, once for each
        # destination thumbnail.
        assert pngcrush_image_mock.call_count == 2
        assert pngcrush_image_mock.call_args_list[0][0][0] == (
            expected_dst1.name)
        assert pngcrush_image_mock.call_args_list[1][0][0] == (
            expected_dst2.name)

        assert image_size(expected_dst1.name) == (680, 100)
        assert image_size(expected_dst2.name) == (32, 32)

        addon.reload()
        self.assertCloseToNow(addon.modified)

    @mock.patch('olympia.addons.tasks.pngcrush_image')
    def test_save_persona_image(self, pngcrush_image_mock):
        # save_persona_image() simply saves an image as a png to the
        # destination file. The image should be processed with pngcrush.
        expected_dst = tempfile.NamedTemporaryFile(
            mode='r+w+b', suffix=".png", delete=False, dir=settings.TMP_PATH)
        save_persona_image(
            get_image_path('persona-header.jpg'),
            expected_dst.name
        )
        # pngcrush_image should have been called once.
        assert pngcrush_image_mock.call_count == 1
        assert pngcrush_image_mock.call_args_list[0][0][0] == expected_dst.name

    @mock.patch('olympia.addons.tasks.pngcrush_image')
    def test_save_persona_image_not_an_image(self, pngcrush_image_mock):
        # If the source is not an image, save_persona_image() should just
        # return early without writing the destination or calling pngcrush.
        expected_dst = tempfile.NamedTemporaryFile(
            mode='r+w+b', suffix=".png", delete=False, dir=settings.TMP_PATH)
        save_persona_image(
            get_image_path('non-image.png'),
            expected_dst.name
        )
        # pngcrush_image should not have been called.
        assert pngcrush_image_mock.call_count == 0
        # the destination file should not have been written to.
        assert os.stat(expected_dst.name).st_size == 0


@pytest.mark.django_db
@mock.patch('olympia.addons.tasks.add_static_theme_from_lwt')
def test_migrate_lwts_to_static_themes(add_static_theme_from_lwt_mock):
    # Include two LWT that won't get migrated sandwiched between some good LWTs
    persona_a = addon_factory(type=amo.ADDON_PERSONA, slug='theme_a')
    persona_none = addon_factory(type=amo.ADDON_PERSONA, slug='theme_none')
    persona_b = addon_factory(type=amo.ADDON_PERSONA, slug='theme_b')
    persona_raise = addon_factory(type=amo.ADDON_PERSONA, slug='theme_raise')
    persona_c = addon_factory(type=amo.ADDON_PERSONA, slug='theme_c')

    addon_a = addon_factory(type=amo.ADDON_STATICTHEME)
    addon_b = addon_factory(type=amo.ADDON_STATICTHEME)
    addon_c = addon_factory(type=amo.ADDON_STATICTHEME)
    add_static_theme_from_lwt_mock.side_effect = [
        addon_a, False, addon_b, Exception('foo'), addon_c]

    # call the migration task, as the command would:
    migrate_lwts_to_static_themes(
        [persona_a.id, persona_none.id, persona_b.id, persona_raise.id,
         persona_c.id])

    assert MigratedLWT.objects.all().count() == 3
    assert Addon.objects.filter(type=amo.ADDON_PERSONA).count() == 2

    persona_a.reload()
    addon_a.reload()
    assert persona_a.status == amo.STATUS_DELETED
    assert MigratedLWT.objects.get(
        lightweight_theme=persona_a).static_theme == addon_a
    assert addon_a.slug == 'theme_a'

    persona_b.reload()
    addon_b.reload()
    assert persona_b.status == amo.STATUS_DELETED
    assert MigratedLWT.objects.get(
        lightweight_theme=persona_b).static_theme == addon_b
    assert addon_b.slug == 'theme_b'

    persona_c.reload()
    addon_c.reload()
    assert persona_c.status == amo.STATUS_DELETED
    assert MigratedLWT.objects.get(
        lightweight_theme=persona_c).static_theme == addon_c
    assert addon_c.slug == 'theme_c'
    assert len(mail.outbox) == 0


@override_settings(ENABLE_ADDON_SIGNING=True)
class TestAddStaticThemeFromLwt(TestCase):
    create_date = datetime(2000, 1, 1, 1, 1, 1)
    modify_date = datetime(2008, 8, 8, 8, 8, 8)
    update_date = datetime(2009, 9, 9, 9, 9, 9)

    def setUp(self):
        super(TestAddStaticThemeFromLwt, self).setUp()
        self.call_signing_mock = self.patch(
            'olympia.lib.crypto.packaged.call_signing')
        self.build_mock = self.patch(
            'olympia.addons.tasks.build_static_theme_xpi_from_lwt')
        self.build_mock.side_effect = self._mock_xpi_side_effect
        self.call_signing_mock.return_value = 'abcdefg1234'
        AppVersion.objects.get_or_create(
            application=amo.FIREFOX.id, version='53.0')
        AppVersion.objects.get_or_create(
            application=amo.FIREFOX.id, version='*')
        user_factory(id=settings.TASK_USER_ID, email='taskuser@mozilla.com')

    def _mock_xpi_side_effect(self, lwt, upload_path):
        xpi_path = os.path.join(
            settings.ROOT,
            'src/olympia/devhub/tests/addons/mozilla_static_theme.zip')
        copy_stored_file(xpi_path, upload_path)
        assert not os.path.isdir(upload_path)
        return mock.DEFAULT

    def _check_result(self, static_theme, authors, tags, categories, license_,
                      ratings):
        # metadata is correct
        assert list(static_theme.authors.all()) == authors
        assert list(static_theme.tags.all()) == tags
        assert len(categories) == 1
        lwt_cat = categories[0]
        static_theme_cats = [
            (cat.name, cat.application) for cat in static_theme.all_categories]
        assert static_theme_cats == [
            (lwt_cat.name, amo.FIREFOX.id), (lwt_cat.name, amo.ANDROID.id)]
        assert static_theme.current_version.license.builtin == license_
        # status is good
        assert static_theme.status == amo.STATUS_PUBLIC
        current_file = static_theme.current_version.files.get()
        assert current_file.status == amo.STATUS_PUBLIC
        # Ratings were migrated
        assert list(Rating.unfiltered.filter(addon=static_theme)) == ratings
        log_entries = ActivityLog.objects.filter(
            action=amo.LOG.ADD_RATING.id, addonlog__addon=static_theme)
        assert log_entries.count() == len(ratings)
        for rating, log_entry in zip(ratings, log_entries):
            arguments = log_entry.arguments
            assert rating in arguments
            assert static_theme in arguments
        # UpdateCounts were copied.
        assert UpdateCount.objects.filter(
            addon_id=static_theme.id).count() == 2
        # xpi was signed
        self.call_signing_mock.assert_called_with(current_file)
        assert current_file.cert_serial_num == 'abcdefg1234'
        assert static_theme.created == self.create_date
        assert static_theme.modified == self.modify_date
        cron.addon_last_updated()  # Make sure the last_updated change stuck.
        assert static_theme.reload().last_updated == self.update_date

    def test_add_static_theme_from_lwt(self):
        author = user_factory()
        persona = addon_factory(
            type=amo.ADDON_PERSONA, users=[author], name='Firefox Theme')
        persona.update(
            created=self.create_date, modified=self.modify_date,
            last_updated=self.update_date)
        persona.persona.license = licenses.LICENSE_CC_BY_ND.id
        Tag.objects.create(tag_text='themey').save_tag(persona)
        License.objects.create(builtin=licenses.LICENSE_CC_BY_ND.builtin)
        rating_user = user_factory()
        rating = Rating.objects.create(
            addon=persona, version=persona.current_version, user=rating_user,
            rating=2, body=u'fooooo', user_responsible=rating_user)
        ThemeUpdateCount.objects.create(
            addon_id=persona.id, date=datetime(2018, 1, 1), count=123)
        ThemeUpdateCount.objects.create(
            addon_id=persona.id, date=datetime(2018, 2, 1), count=456)
        # Create a count for an addon that shouldn't be migrated too.
        ThemeUpdateCount.objects.create(
            addon_id=addon_factory().id, date=datetime(2018, 2, 1), count=45)

        static_theme = add_static_theme_from_lwt(persona)

        self._check_result(
            static_theme, [author], list(persona.tags.all()),
            persona.all_categories, licenses.LICENSE_CC_BY_ND.builtin,
            [rating])

    def test_add_static_theme_broken_lwt(self):
        """What if no author or license or category?"""
        persona = addon_factory(type=amo.ADDON_PERSONA)
        persona.update(
            created=self.create_date, modified=self.modify_date,
            last_updated=self.update_date)

        assert list(persona.authors.all()) == []  # no author
        persona.persona.license = None  # no license
        AddonCategory.objects.filter(addon=persona).delete()
        assert persona.all_categories == []  # no category
        License.objects.create(builtin=licenses.LICENSE_COPYRIGHT_AR.builtin)
        rating_user = user_factory()
        rating = Rating.objects.create(
            addon=persona, version=persona.current_version, user=rating_user,
            rating=2, body=u'fooooo', user_responsible=rating_user)
        rating.delete()  # delete the rating - should still be migrated.
        # Add 2 more Ratings for different addons that shouldn't be copied.
        Rating.objects.create(
            addon=addon_factory(), user=rating_user,
            rating=3, body=u'tgd', user_responsible=rating_user)
        Rating.objects.create(
            addon=addon_factory(), user=rating_user,
            rating=4, body=u'tgffd', user_responsible=rating_user)
        ThemeUpdateCount.objects.create(
            addon_id=persona.id, date=datetime(2018, 1, 1), count=123)
        ThemeUpdateCount.objects.create(
            addon_id=persona.id, date=datetime(2018, 2, 1), count=456)
        # Create a count for an addon that shouldn't be migrated too.
        ThemeUpdateCount.objects.create(
            addon_id=addon_factory().id, date=datetime(2018, 2, 1), count=45)

        static_theme = add_static_theme_from_lwt(persona)

        default_author = UserProfile.objects.get(
            email=settings.MIGRATED_LWT_DEFAULT_OWNER_EMAIL)
        desktop_default_category = (
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_STATICTHEME]['other'])
        android_default_category = (
            CATEGORIES[amo.ANDROID.id][amo.ADDON_STATICTHEME]['other'])
        self._check_result(
            static_theme, [default_author], [], [desktop_default_category],
            licenses.LICENSE_COPYRIGHT_AR.builtin, [rating])
        # Double check its the exact category we want.
        assert static_theme.all_categories == [
            desktop_default_category, android_default_category]


@override_settings(ENABLE_ADDON_SIGNING=True)
class TestMigrateLegacyDictionaryToWebextension(TestCase):
    def setUp(self):
        self.user = user_factory(
            id=settings.TASK_USER_ID, username='taskuser',
            email='taskuser@mozilla.com')
        with freeze_time('2017-07-27 07:00'):
            self.addon = addon_factory(
                type=amo.ADDON_DICT,
                guid='@my-dict',  # Same id used in dict-webext.xpi.
                version_kw={'version': '6.3'})

        AppVersion.objects.get_or_create(
            application=amo.FIREFOX.id, version='61.0')
        AppVersion.objects.get_or_create(
            application=amo.FIREFOX.id, version='*')

        self.call_signing_mock = self.patch(
            'olympia.lib.crypto.packaged.call_signing')
        self.call_signing_mock.return_value = 'abcdefg1234'

        self.build_mock = self.patch(
            'olympia.addons.tasks.build_webext_dictionary_from_legacy')
        self.build_mock.side_effect = self._mock_xpi_side_effect

    def _mock_xpi_side_effect(self, addon, destination):
        xpi_path = os.path.join(
            settings.ROOT, 'src/olympia/files/fixtures/files/dict-webext.xpi')
        copy_stored_file(xpi_path, destination)
        assert not os.path.isdir(destination)
        return mock.DEFAULT

    def test_basic(self):
        assert not FileUpload.objects.exists()
        assert not ActivityLog.objects.filter(
            action=amo.LOG.ADD_VERSION.id).exists()
        old_version = self.addon.current_version

        self.build_mock.return_value = 'fake-locale'

        with freeze_time('2018-08-28 08:00'):
            self.migration_date = datetime.now()
            migrate_legacy_dictionary_to_webextension(self.addon)

        self.build_mock.assert_called_once_with(self.addon, mock.ANY)
        assert FileUpload.objects.exists()
        self.addon.reload()
        assert self.addon.target_locale == 'fake-locale'
        assert self.addon.current_version != old_version
        activity_log = ActivityLog.objects.filter(
            action=amo.LOG.ADD_VERSION.id).get()
        assert activity_log.arguments == [
            self.addon.current_version, self.addon
        ]

        assert self.addon.last_updated == self.migration_date

        current_file = self.addon.current_version.all_files[0]
        assert current_file.datestatuschanged == self.migration_date
        assert current_file.status == amo.STATUS_PUBLIC

        self.call_signing_mock.assert_called_with(current_file)
        assert current_file.cert_serial_num == 'abcdefg1234'


class TestMigrateWebextensionsToGitStorage(TestCase):
    def test_basic(self):
        addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})

        migrate_webextensions_to_git_storage([addon.pk])

        repo = AddonGitRepository(addon.pk)

        assert repo.git_repository_path == os.path.join(
            settings.GIT_FILE_STORAGE_PATH, id_to_path(addon.id), 'package')
        assert os.listdir(repo.git_repository_path) == ['.git']

    @mock.patch('olympia.versions.tasks.extract_version_to_git')
    def test_no_files(self, extract_mock):
        addon = addon_factory()
        addon.current_version.files.all().delete()

        migrate_webextensions_to_git_storage([addon.pk])

        extract_mock.assert_not_called()

    @mock.patch('olympia.versions.tasks.extract_version_to_git')
    def test_skip_already_migrated_versions(self, extract_mock):
        addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
        version_to_migrate = addon.current_version
        already_migrated_version = version_factory(
            addon=addon, file_kw={'filename': 'webextension_no_id.xpi'})
        already_migrated_version.update(git_hash='already migrated...')

        migrate_webextensions_to_git_storage([addon.pk])

        # Only once instead of twice
        extract_mock.assert_called_once_with(version_to_migrate.pk)

    @mock.patch('olympia.versions.tasks.extract_version_to_git')
    def test_migrate_versions_from_old_to_new(self, extract_mock):
        addon = addon_factory(file_kw={'filename': 'webextension_no_id.xpi'})
        oldest_version = addon.current_version
        oldest_version.update(created=self.days_ago(6))
        older_version = version_factory(
            created=self.days_ago(5),
            addon=addon, file_kw={'filename': 'webextension_no_id.xpi'})
        most_recent = version_factory(
            created=self.days_ago(2),
            addon=addon, file_kw={'filename': 'webextension_no_id.xpi'})

        migrate_webextensions_to_git_storage([addon.pk])

        # Only once instead of twice
        assert extract_mock.call_count == 3
        assert extract_mock.call_args_list[0][0][0] == oldest_version.pk
        assert extract_mock.call_args_list[1][0][0] == older_version.pk
        assert extract_mock.call_args_list[2][0][0] == most_recent.pk
