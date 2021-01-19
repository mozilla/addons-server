from django.test.utils import override_settings

from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.amo.tests import addon_factory, TestCase
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.serializers import DiscoverySerializer
from olympia.translations.models import Translation


class TestDiscoverySerializer(TestCase):
    def serialize(self, item, lang=None):
        request = APIRequestFactory().get('/' if not lang else f'/?lang={lang}')
        request.version = 'v5'
        return DiscoverySerializer(context={'request': request}).to_representation(item)

    def test_description_text_custom(self):
        addon = addon_factory(summary='Foo', description='Bar')
        item = DiscoveryItem.objects.create(
            addon=addon, custom_description='Custôm Desc.'
        )
        assert self.serialize(item)['description_text'] == {'en-US': 'Custôm Desc.'}
        with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
            assert self.serialize(item)['description_text'] == 'Custôm Desc.'

        # and repeat with a lang specified
        with self.activate('fr'):
            item.reload()
            assert self.serialize(item, 'fr')['description_text'] == {
                'en-US': 'Custôm Desc.',
                'fr': None,
                '_default': 'en-US',
            }
            with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
                assert self.serialize(item, 'fr')['description_text'] == 'Custôm Desc.'

    def test_description_text_custom_empty(self):
        addon = addon_factory(summary='')
        item = DiscoveryItem.objects.create(addon=addon)
        assert self.serialize(item)['description_text'] is None
        with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
            assert self.serialize(item)['description_text'] == ''
        # with a lang specified
        with self.activate('fr'):
            item.reload()
            assert self.serialize(item, 'fr')['description_text'] is None
            with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
                assert self.serialize(item, 'fr')['description_text'] == ''

    def test_description_text_custom_extension(self):
        addon = addon_factory(summary='Mÿ Summary')
        # Add a summary in fr too
        Translation.objects.create(
            id=addon.summary.id, locale='fr', localized_string='Mes Summáry'
        )
        item = DiscoveryItem.objects.create(addon_id=addon.id)

        assert self.serialize(item)['description_text'] == {
            'en-US': 'Mÿ Summary',
            'fr': 'Mes Summáry',
        }
        with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
            assert self.serialize(item)['description_text'] == 'Mÿ Summary'

        # with lang specified that we *don't* have a translation for
        with self.activate('de'):
            item.reload()
            assert self.serialize(item, 'de')['description_text'] == {
                'en-US': 'Mÿ Summary',
                'de': None,
                '_default': 'en-US',
            }
            with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
                assert self.serialize(item, 'fr')['description_text'] == 'Mÿ Summary'

        # and then with a lang specified that we *do* have a translation for
        with self.activate('fr'):
            item.reload()
            assert self.serialize(item, 'fr')['description_text'] == {
                'fr': 'Mes Summáry',
            }
            with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
                assert self.serialize(item, 'fr')['description_text'] == 'Mes Summáry'

    def test_description_text_custom_not_extension(self):
        item = DiscoveryItem.objects.create(addon=addon_factory(type=amo.ADDON_DICT))
        assert self.serialize(item)['description_text'] is None
        with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
            assert self.serialize(item)['description_text'] == ''

        # and repeat with a lang specified
        with self.activate('fr'):
            item.reload()
            assert self.serialize(item, 'fr')['description_text'] is None
            with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
                assert self.serialize(item, 'fr')['description_text'] == ''
