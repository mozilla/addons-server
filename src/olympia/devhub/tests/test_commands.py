import mock
import os

from django.core.management import call_command

from olympia import amo
from olympia.addons.models import Preview
from olympia.amo.tests import addon_factory, TestCase
from olympia.devhub.management.commands import crush_images_for_top_addons


class TestCrushImagesForTopAddons(TestCase):
    @mock.patch('olympia.devhub.tasks.pngcrush_image')
    def test_crush_icons(self, pngcrush_image_mock):
        addon1 = addon_factory(icon_type='image/png')
        icon_dir = addon1.get_icon_dir()
        crush_images_for_top_addons.Command().crush_addons([addon1])
        assert pngcrush_image_mock.call_count == 2
        assert pngcrush_image_mock.call_args_list[0][0][0] == os.path.join(
            icon_dir, '%s-64.png' % addon1.pk
        )
        assert pngcrush_image_mock.call_args_list[1][0][0] == os.path.join(
            icon_dir, '%s-32.png' % addon1.pk
        )

    @mock.patch('olympia.devhub.tasks.pngcrush_image')
    def test_crush_nothing(self, pngcrush_image_mock):
        addon1 = addon_factory()  # No previews or icons to crush here.
        crush_images_for_top_addons.Command().crush_addons([addon1])
        assert pngcrush_image_mock.call_count == 0

    @mock.patch('olympia.devhub.tasks.pngcrush_image')
    def test_crush_previews(self, pngcrush_image_mock):
        addon1 = addon_factory()
        preview1 = Preview.objects.create(addon=addon1)
        crush_images_for_top_addons.Command().crush_addons([addon1])
        assert pngcrush_image_mock.call_count == 2
        assert pngcrush_image_mock.call_args_list[0][0][0] == (
            preview1.thumbnail_path
        )
        assert pngcrush_image_mock.call_args_list[1][0][0] == (
            preview1.image_path
        )

    @mock.patch('olympia.devhub.tasks.pngcrush_image')
    def test_crush_new_but_weird_persona(self, pngcrush_image_mock):
        addon1 = addon_factory(type=amo.ADDON_PERSONA)
        persona = addon1.persona
        persona.persona_id = 0
        persona.save()
        crush_images_for_top_addons.Command().crush_addons([addon1])
        assert pngcrush_image_mock.call_count == 2
        assert pngcrush_image_mock.call_args_list[0][0][0] == (
            persona.preview_path
        )
        assert pngcrush_image_mock.call_args_list[1][0][0] == (
            persona.icon_path
        )

    @mock.patch('olympia.devhub.tasks.pngcrush_image')
    def test_crush_new_persona_with_headerfooter(self, pngcrush_image_mock):
        addon1 = addon_factory(type=amo.ADDON_PERSONA)
        persona = addon1.persona
        persona.persona_id = 0
        persona.header = 'header.png'
        persona.footer = 'footer.png'
        persona.save()
        crush_images_for_top_addons.Command().crush_addons([addon1])
        assert pngcrush_image_mock.call_count == 4
        assert pngcrush_image_mock.call_args_list[0][0][0] == (
            persona.preview_path
        )
        assert pngcrush_image_mock.call_args_list[1][0][0] == (
            persona.icon_path
        )
        assert pngcrush_image_mock.call_args_list[2][0][0] == (
            persona.header_path
        )
        assert pngcrush_image_mock.call_args_list[3][0][0] == (
            persona.footer_path
        )

    @mock.patch('olympia.devhub.tasks.pngcrush_image')
    def test_crush_old_persona(self, pngcrush_image_mock):
        addon1 = addon_factory(type=amo.ADDON_PERSONA)
        crush_images_for_top_addons.Command().crush_addons([addon1])
        assert pngcrush_image_mock.call_count == 0

    @mock.patch('olympia.devhub.tasks.pngcrush_image')
    def test_full_run(self, pngcrush_image_mock):
        addon1 = addon_factory(icon_type='image/png')
        Preview.objects.create(addon=addon1)
        Preview.objects.create(addon=addon1)
        addon2 = addon_factory(type=amo.ADDON_PERSONA)
        persona = addon2.persona
        persona.persona_id = 0
        persona.header = 'header.png'
        persona.footer = 'footer.png'
        persona.save()

        call_command('crush_images_for_top_addons')
        # 10 calls:
        # - 2 icons sizes for the extension
        # - 2 sizes for each of the 2 previews of the extension
        # - 1 icon and 1 preview for the persona, plus 1 header and 1 footer.
        assert pngcrush_image_mock.call_count == 10

    @mock.patch('olympia.devhub.tasks.pngcrush_image')
    def test_dry_run(self, pngcrush_image_mock):
        addon_factory()
        call_command('crush_images_for_top_addons', dry_run=True)
        assert pngcrush_image_mock.call_count == 0
