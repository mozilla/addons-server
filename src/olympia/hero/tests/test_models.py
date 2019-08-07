from django.core.exceptions import ValidationError

from olympia.amo.tests import addon_factory, TestCase
from olympia.hero.models import PrimaryHero, SecondaryHero
from olympia.discovery.models import DiscoveryItem


class TestPrimaryHero(TestCase):
    def test_image_path(self):
        ph = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(addon=addon_factory()),
            image='foo.png')
        assert ph.image_path == (
            'http://testserver/static/img/hero/featured/foo.png')

    def test_gradiant(self):
        ph = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(addon=addon_factory()),
            gradient_color='#112233')
        assert ph.gradient == {'start': '#20123A', 'end': '#112233'}

    def test_clean(self):
        ph = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(addon=addon_factory()))
        assert not ph.enabled
        ph.clean()  # it raises if there's an error
        ph.enabled = True
        with self.assertRaises(ValidationError):
            ph.clean()

        assert ph.disco_addon.recommended_status != ph.disco_addon.RECOMMENDED
        ph.disco_addon.update(recommendable=True)
        ph.disco_addon.addon.current_version.update(
            recommendation_approved=True)
        assert ph.disco_addon.recommended_status == ph.disco_addon.RECOMMENDED
        ph.clean()  # it raises if there's an error

    def test_clean_external(self):
        ph = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(addon=addon_factory()),
            is_external=True)
        assert not ph.enabled
        ph.clean()  # it raises if there's an error
        ph.enabled = True
        with self.assertRaises(ValidationError):
            ph.clean()

        ph.disco_addon.addon.homepage = 'https://foobar.com/'
        ph.disco_addon.addon.save()
        ph.clean()  # it raises if there's an error


class TestSecondaryHero(TestCase):
    def test_str(self):
        sh = SecondaryHero.objects.create(
            headline='Its a héadline!', description='description')
        assert str(sh) == 'Its a héadline!'

    def test_clean(self):
        ph = SecondaryHero.objects.create()
        assert not ph.enabled
        ph.clean()  # it raises if there's an error

        # neither cta_url or cta_text are set, and that's okay.
        ph.enabled = True
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

        # No error if not enabled.
        ph.enabled = False
        ph.clean()  # it raises if there's an error

        # And setting both is okay too.
        ph.enabled = True
        ph.cta_url = 'http://goo.gl'
        ph.clean()  # it raises if there's an error
