from olympia import amo
from olympia.amo.tests import addon_factory, TestCase
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.amo.urlresolvers import get_outgoing_url
from olympia.constants.promoted import RECOMMENDED
from olympia.promoted.models import PromotedAddon

from ..models import (
    GRADIENT_START_COLOR,
    PrimaryHero,
    PrimaryHeroImage,
    SecondaryHero,
    SecondaryHeroModule,
)
from ..serializers import (
    ExternalAddonSerializer,
    HeroAddonSerializer,
    PrimaryHeroShelfSerializer,
    SecondaryHeroShelfSerializer,
)


class TestPrimaryHeroShelfSerializer(TestCase):
    def setUp(self):
        uploaded_photo = get_uploaded_file('transparent.png')
        self.phi = PrimaryHeroImage.objects.create(custom_image=uploaded_photo)
        self.image = 'http://testserver/user-media/hero-featured-image/transparent.jpg'

    def test_basic(self):
        addon = addon_factory(promoted=RECOMMENDED)
        hero = PrimaryHero.objects.create(
            promoted_addon=addon.promotedaddon,
            description='Déscription',
            select_image=self.phi,
            gradient_color='#008787',
        )
        data = PrimaryHeroShelfSerializer(instance=hero).data
        assert data == {
            'featured_image': self.image,
            'description': 'Déscription',
            'gradient': {'start': GRADIENT_START_COLOR[1], 'end': 'color-green-70'},
            'addon': HeroAddonSerializer(instance=addon).data,
        }
        assert data['addon']['promoted'] == {
            'apps': [amo.FIREFOX.short, amo.ANDROID.short],
            'category': RECOMMENDED.api_name,
        }

    def test_description(self):
        addon = addon_factory(type=amo.ADDON_STATICTHEME, summary=None)
        hero = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon),
            description='hero description',
        )
        data = PrimaryHeroShelfSerializer(instance=hero).data
        assert data['description'] == 'hero description'

        hero.update(description='')
        data = PrimaryHeroShelfSerializer(instance=hero).data
        assert data['description'] == ''

        # falls back to the addon summary if one is available
        addon.summary = 'addon summary'
        addon.save()
        data = PrimaryHeroShelfSerializer(instance=hero).data
        assert data['description'] == 'addon summary'

    def test_external_addon(self):
        addon = addon_factory(
            summary='Summary',
            homepage='https://foo.baa',
            version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED},
        )
        hero = PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon),
            select_image=self.phi,
            gradient_color='#008787',
            is_external=True,
        )
        assert PrimaryHeroShelfSerializer(instance=hero).data == {
            'featured_image': self.image,
            'description': 'Summary',
            'gradient': {'start': GRADIENT_START_COLOR[1], 'end': 'color-green-70'},
            'external': ExternalAddonSerializer(instance=addon).data,
        }
        assert ExternalAddonSerializer(instance=addon).data == {
            'id': addon.id,
            'guid': addon.guid,
            'homepage': {
                'url': {'en-US': str(addon.homepage)},
                'outgoing': {'en-US': get_outgoing_url(str(addon.homepage))},
            },
            'name': {'en-US': str(addon.name)},
            'type': 'extension',
        }


class TestSecondaryHeroShelfSerializer(TestCase):
    def test_basic(self):
        hero = SecondaryHero.objects.create(
            headline='Its a héadline!', description='description'
        )
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
                'outgoing': 'http://testserver/extensions/',
                'text': 'Go here',
            },
            'modules': [],
        }
        hero.update(cta_url='https://goo.gl/stuff/', cta_text='Googl here')
        data = SecondaryHeroShelfSerializer(instance=hero).data
        assert data == {
            'headline': 'Its a héadline!',
            'description': 'description',
            'cta': {
                'url': 'https://goo.gl/stuff/',
                'outgoing': get_outgoing_url('https://goo.gl/stuff/'),
                'text': 'Googl here',
            },
            'modules': [],
        }

    def test_with_modules(self):
        hero = SecondaryHero.objects.create()
        promos = [
            SecondaryHeroModule.objects.create(
                description='It does things!', shelf=hero, icon='a.svg'
            ),
            SecondaryHeroModule.objects.create(
                shelf=hero, cta_url='/extensions/', cta_text='Go here', icon='b.svg'
            ),
            SecondaryHeroModule.objects.create(shelf=hero, icon='c.svg'),
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
                        'outgoing': 'http://testserver/extensions/',
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
