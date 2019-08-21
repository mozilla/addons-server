from olympia import amo
from olympia.amo.tests import addon_factory, TestCase
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.serializers import DiscoveryAddonSerializer

from ..models import (
    GRADIENT_START_COLOR, PrimaryHero, SecondaryHero, SecondaryHeroModule)
from ..serializers import (
    ExternalAddonSerializer, PrimaryHeroShelfSerializer,
    SecondaryHeroShelfSerializer)


class TestPrimaryHeroShelfSerializer(TestCase):
    def test_basic(self):
        addon = addon_factory()
        hero = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(
                addon=addon, custom_description='Déscription'),
            image='foo.png',
            gradient_color='#068989')
        data = PrimaryHeroShelfSerializer(instance=hero).data
        assert data == {
            'featured_image': (
                'http://testserver/static/img/hero/featured/foo.png'),
            'description': '<blockquote>Déscription</blockquote>',
            'gradient': {
                'start': GRADIENT_START_COLOR[1],
                'end': 'green-70'
            },
            'addon': DiscoveryAddonSerializer(instance=addon).data,
        }

    def test_external_addon(self):
        addon = addon_factory(
            summary='Summary', homepage='https://foo.baa', version_kw={
                'channel': amo.RELEASE_CHANNEL_UNLISTED})
        hero = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(addon=addon),
            image='foo.png',
            gradient_color='#068989',
            is_external=True)
        assert PrimaryHeroShelfSerializer(instance=hero).data == {
            'featured_image': (
                'http://testserver/static/img/hero/featured/foo.png'),
            'description': '<blockquote>Summary</blockquote>',
            'gradient': {
                'start': GRADIENT_START_COLOR[1],
                'end': 'green-70'
            },
            'external': ExternalAddonSerializer(instance=addon).data,
        }
        assert ExternalAddonSerializer(instance=addon).data == {
            'id': addon.id,
            'guid': addon.guid,
            'homepage': {'en-US': str(addon.homepage)},
            'name': {'en-US': str(addon.name)},
            'type': 'extension',
        }


class TestSecondaryHeroShelfSerializer(TestCase):
    def test_basic(self):
        hero = SecondaryHero.objects.create(
            headline='Its a héadline!', description='description')
        data = SecondaryHeroShelfSerializer(instance=hero).data
        assert data == {
            'headline': 'Its a héadline!',
            'description': 'description',
            'cta': None,
            'modules': [],
        }
        hero.update(cta_url='/extensions/', cta_text='Go here')
        data = SecondaryHeroShelfSerializer(instance=hero).data
        assert data == {
            'headline': 'Its a héadline!',
            'description': 'description',
            'cta': {
                'url': 'http://testserver/extensions/',
                'text': 'Go here',
            },
            'modules': [],
        }

    def test_with_modules(self):
        hero = SecondaryHero.objects.create()
        promos = [
            SecondaryHeroModule.objects.create(
                description='It does things!', shelf=hero, icon='a.svg'),
            SecondaryHeroModule.objects.create(
                shelf=hero, cta_url='/extensions/', cta_text='Go here',
                icon='b.svg'),
            SecondaryHeroModule.objects.create(
                shelf=hero, icon='c.svg'),
        ]
        data = SecondaryHeroShelfSerializer(instance=hero).data
        assert data == {
            'headline': '',
            'description': '',
            'cta': None,
            'modules': [
                {
                    'description': promos[0].description,
                    'icon': 'http://testserver/static/img/hero/icons/a.svg',
                    'cta': None,
                },
                {
                    'description': '',
                    'icon': 'http://testserver/static/img/hero/icons/b.svg',
                    'cta': {
                        'url': 'http://testserver/extensions/',
                        'text': 'Go here',
                    },
                },
                {
                    'description': '',
                    'icon': 'http://testserver/static/img/hero/icons/c.svg',
                    'cta': None,
                },
            ],
        }
