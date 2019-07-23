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
