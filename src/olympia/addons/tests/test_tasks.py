import mock
import os
import shutil
import tempfile

from django.conf import settings

from waffle.testutils import override_switch

from olympia import amo
from olympia.addons.models import AddonCategory, MigratedLWT
from olympia.addons.tasks import (
    add_static_theme_from_lwt, create_persona_preview_images,
    migrate_lwts_to_static_themes, save_persona_image)
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import image_size
from olympia.constants import licenses
from olympia.constants.categories import CATEGORIES
from olympia.tags.models import Tag
from olympia.versions.models import License


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
            set_modified_on=[addon],
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


class TestMigrateLightweightThemesToStaticThemes(TestCase):

    @mock.patch('olympia.addons.tasks.add_static_theme_from_lwt')
    def test_migrate_lwts(self, add_static_theme_from_lwt_mock):
        persona_a = addon_factory(type=amo.ADDON_PERSONA, slug='theme_a')
        persona_b = addon_factory(type=amo.ADDON_PERSONA, slug='theme_b')
        addon_a = addon_factory(type=amo.ADDON_STATICTHEME)
        addon_b = addon_factory(type=amo.ADDON_STATICTHEME)
        add_static_theme_from_lwt_mock.side_effect = [addon_a, addon_b]

        # call the migration task, as the command would:
        migrate_lwts_to_static_themes([persona_a.id, persona_b.id])

        assert MigratedLWT.objects.all().count() == 2

        persona_a.reload()
        addon_a.reload()
        assert persona_a.status == amo.STATUS_DELETED
        assert MigratedLWT.objects.get(
            lightweight_theme=persona_a).static_theme == addon_a
        assert addon_a.slug == 'theme_a'

        persona_b.reload()
        addon_a.reload()
        assert persona_b.status == amo.STATUS_DELETED
        assert MigratedLWT.objects.get(
            lightweight_theme=persona_b).static_theme == addon_b
        assert addon_b.slug == 'theme_b'

    @mock.patch('olympia.addons.tasks.build_static_theme_xpi_from_lwt')
    @override_switch('allow-static-theme-uploads', active=True)
    def test_add_static_theme_from_lwt(self, build_static_theme_xpi_mock):
        xpi_path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        copy_path = os.path.join(
            settings.TMP_PATH, 'static_theme.zip')
        shutil.copy(xpi_path, copy_path)
        author = user_factory()
        build_static_theme_xpi_mock.return_value = file(copy_path)
        persona = addon_factory(type=amo.ADDON_PERSONA, users=[author])
        persona.persona.license = licenses.LICENSE_CC_BY_ND.id
        Tag.objects.create(tag_text='themey').save_tag(persona)
        License.objects.create(builtin=licenses.LICENSE_CC_BY_ND.builtin)

        static_theme = add_static_theme_from_lwt(persona)

        assert list(static_theme.authors.all()) == [author]
        assert [cat.name for cat in static_theme.all_categories] == [
            cat.name for cat in persona.all_categories]
        assert list(static_theme.tags.all()) == list(persona.tags.all())
        assert static_theme.current_version.license.builtin == (
            licenses.LICENSE_CC_BY_ND.builtin)
        assert static_theme.status == amo.STATUS_PUBLIC
        assert static_theme.current_version.files.get().status == (
            amo.STATUS_PUBLIC)

    @mock.patch('olympia.addons.tasks.build_static_theme_xpi_from_lwt')
    @override_switch('allow-static-theme-uploads', active=True)
    def test_add_static_theme_broken_lwt(self, build_static_theme_xpi_mock):
        """What if no author or license or category?"""
        user_factory(id=settings.TASK_USER_ID)  # used when LWT has no author.
        xpi_path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        copy_path = os.path.join(
            settings.TMP_PATH, 'static_theme.zip')
        shutil.copy(xpi_path, copy_path)
        build_static_theme_xpi_mock.return_value = file(copy_path)
        persona = addon_factory(type=amo.ADDON_PERSONA)

        assert list(persona.authors.all()) == []  # no author
        persona.persona.license = None  # no license
        AddonCategory.objects.filter(addon=persona).delete()
        assert persona.all_categories == []  # no category
        License.objects.create(builtin=licenses.LICENSE_COPYRIGHT_AR.builtin)

        static_theme = add_static_theme_from_lwt(persona)

        assert list(static_theme.authors.all()) == []
        assert static_theme.all_categories == [
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_STATICTHEME]['other']]
        assert list(static_theme.tags.all()) == []
        assert static_theme.current_version.license.builtin == (
            licenses.LICENSE_COPYRIGHT_AR.builtin)
        assert static_theme.status == amo.STATUS_PUBLIC
        assert static_theme.current_version.files.get().status == (
            amo.STATUS_PUBLIC)
