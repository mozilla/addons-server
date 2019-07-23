from olympia.amo.tests import addon_factory, TestCase
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.serializers import DiscoveryAddonSerializer

from ..models import GRADIENT_START_COLOR, PrimaryHero
from ..serializers import PrimaryHeroShelfSerializer


class TestPrimaryHeroShelfSerializer(TestCase):
    def test_basic(self):
        addon = addon_factory(summary='Summary')
        hero = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(
                addon=addon,
                custom_heading='Its a héading!'),
            image='foo.png',
            gradient_color='#123456')
        data = PrimaryHeroShelfSerializer(instance=hero).data
        assert data == {
            'featured_image': hero.image_path,
            'heading': 'Its a héading!',
            'description': '<blockquote>Summary</blockquote>',
            'gradient': {
                'start': GRADIENT_START_COLOR,
                'end': '#123456'
            },
            'addon': DiscoveryAddonSerializer(instance=addon).data,
        }
