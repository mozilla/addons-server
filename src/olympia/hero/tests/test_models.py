from django.core.exceptions import ValidationError

from olympia.amo.tests import addon_factory, TestCase
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.constants.promoted import RECOMMENDED
from olympia.hero.models import (
    PrimaryHero, PrimaryHeroImage, SecondaryHero, SecondaryHeroModule)
from olympia.promoted.models import PromotedAddon, PromotedApproval


class TestPrimaryHero(TestCase):
    def setUp(self):
        uploaded_photo = get_uploaded_file('transparent.png')
        self.phi = PrimaryHeroImage.objects.create(custom_image=uploaded_photo)

    def test_image_url(self):
        ph = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            select_image=self.phi)
        assert ph.image_url == (
            'http://testserver/user-media/hero-featured-image/transparent.jpg')
        ph.update(select_image=None)
        assert ph.image_url is None

    def test_gradiant(self):
        ph = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            gradient_color='#C60084')
        assert ph.gradient == {'start': 'color-ink-80', 'end': 'color-pink-70'}

    def test_clean_requires_recommended(self):
        ph = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(), group_id=RECOMMENDED.id),
            gradient_color='#C60184', select_image=self.phi)
        assert not ph.enabled
        ph.clean()  # it raises if there's an error
        ph.enabled = True
        with self.assertRaises(ValidationError):
            ph.clean()

        assert not ph.promoted_addon.addon.is_promoted(group=RECOMMENDED)
        PromotedApproval.objects.create(
            version=ph.promoted_addon.addon.current_version,
            group_id=RECOMMENDED.id)
        assert ph.promoted_addon.addon.is_promoted(group=RECOMMENDED)
        ph.clean()  # it raises if there's an error

    def test_clean_external_requires_homepage(self):
        ph = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            is_external=True, gradient_color='#C60184', select_image=self.phi)
        assert not ph.enabled
        ph.clean()  # it raises if there's an error
        ph.enabled = True
        with self.assertRaises(ValidationError):
            ph.clean()

        ph.promoted_addon.addon.homepage = 'https://foobar.com/'
        ph.promoted_addon.addon.save()
        ph.clean()  # it raises if there's an error

    def test_clean_gradient_and_image(self):
        # Currently, gradient is required and image isn't.
        ph = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(), group_id=RECOMMENDED.id))
        PromotedApproval.objects.create(
            version=ph.promoted_addon.addon.current_version,
            group_id=RECOMMENDED.id)
        assert not ph.enabled
        ph.clean()  # it raises if there's an error
        ph.enabled = True
        with self.assertRaises(ValidationError) as ve:
            ph.clean()
        assert 'gradient_color' in ve.exception.error_dict
        assert 'select_image' not in ve.exception.error_dict

        ph.update(select_image=self.phi)
        with self.assertRaises(ValidationError) as ve:
            ph.clean()
        assert 'gradient_color' in ve.exception.error_dict
        assert 'select_image' not in ve.exception.error_dict

        ph.update(select_image=None, gradient_color='#123456')
        ph.clean()  # it raises if there's an error

    def test_clean_only_enabled(self):
        hero = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(
                addon=addon_factory(), group_id=RECOMMENDED.id),
            gradient_color='#C60184', select_image=self.phi)
        PromotedApproval.objects.create(
            version=hero.promoted_addon.addon.current_version,
            group_id=RECOMMENDED.id)
        assert not hero.enabled
        assert not PrimaryHero.objects.filter(enabled=True).exists()
        # It should still validate even if there are no other enabled shelves,
        # because we're not changing its enabled state.
        hero.clean()  # it raises if there's an error

        # Enabling the shelf is fine.
        hero.enabled = True
        hero.clean()  # it raises if there's an error
        hero.save()

        # Disabling it again is not.
        hero.enabled = False
        with self.assertRaises(ValidationError):
            hero.clean()

        # But if there's another shelf enabled, then it's fine to disable.
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            enabled=True)
        hero.clean()


class TestSecondaryHero(TestCase):

    def test_str(self):
        sh = SecondaryHero.objects.create(
            headline='Its a héadline!', description='description')
        assert str(sh) == 'Its a héadline!'

    def test_clean_cta(self):
        hero = SecondaryHero.objects.create()
        assert not hero.enabled
        hero.clean()  # it raises if there's an error

        # neither cta_url or cta_text are set, and that's okay.
        hero.enabled = True
        hero.clean()  # it raises if there's an error.

        # just set the url without the text is invalid when enabled though.
        hero.cta_url = 'http://goo.gl/'
        with self.assertRaises(ValidationError):
            hero.clean()
        hero.cta_url = None
        hero.cta_text = 'click it!'
        with self.assertRaises(ValidationError):
            hero.clean()
        hero.cta_url = ''
        with self.assertRaises(ValidationError):
            hero.clean()

        # No error if not enabled.
        hero.enabled = False
        hero.clean()  # it raises if there's an error

        # And setting both is okay too.
        hero.enabled = True
        hero.cta_url = 'http://goo.gl'
        hero.clean()  # it raises if there's an error

    def test_clean_only_enabled(self):
        hero = SecondaryHero.objects.create(
            headline='Its a héadline!', description='description')
        assert not hero.enabled
        assert not SecondaryHero.objects.filter(enabled=True).exists()
        # It should still validate even if there are no other enabled shelves,
        # because we're not changing its enabled state.
        hero.clean()  # it raises if there's an error

        # Enabling the shelf is fine.
        hero.enabled = True
        hero.clean()  # it raises if there's an error
        hero.save()

        # Disabling it again is not.
        hero.enabled = False
        with self.assertRaises(ValidationError):
            hero.clean()

        # But if there's another shelf enabled, then it's fine to disable.
        SecondaryHero.objects.create(
            headline='Its a héadline!', description='description',
            enabled=True)
        hero.clean()


class TestSecondaryHeroModule(TestCase):

    def test_str(self):
        shm = SecondaryHeroModule.objects.create(
            description='descríption',
            shelf=SecondaryHero.objects.create())
        assert str(shm) == 'descríption'

    def test_clean_cta(self):
        ph = SecondaryHeroModule.objects.create(
            shelf=SecondaryHero.objects.create())

        # neither cta_url or cta_text are set, and that's okay.
        ph.clean()  # it raises if there's an error.

        # just set the url without the text is invalid when enabled though.
        ph.cta_url = 'http://goo.gl/'
        with self.assertRaises(ValidationError):
            ph.clean()
        ph.cta_url = None
        ph.cta_text = 'click it!'
        with self.assertRaises(ValidationError):
            ph.clean()
        ph.cta_url = ''
        with self.assertRaises(ValidationError):
            ph.clean()

        # And setting both is okay too.
        ph.cta_url = 'http://goo.gl'
        ph.clean()  # it raises if there's an error

    def test_icon_url(self):
        ph = SecondaryHeroModule.objects.create(
            shelf=SecondaryHero.objects.create(),
            icon='foo.svg')
        assert ph.icon_url == (
            'http://testserver/static/img/hero/icons/foo.svg')
