from django.core.exceptions import ValidationError

from olympia.amo.tests import addon_factory, TestCase
from olympia.hero.models import PrimaryHero
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
