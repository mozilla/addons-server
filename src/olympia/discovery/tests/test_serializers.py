from django.test.utils import override_settings

import pytest
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.serializers import DiscoverySerializer
from olympia.translations.models import Translation


class TestDiscoverySerializer(TestCase):
    def serialize(self, item, lang=None):
        request = APIRequestFactory().get('/' if not lang else f'/?lang={lang}')
        request.version = 'v5'
        return DiscoverySerializer(context={'request': request}).to_representation(item)

    @pytest.mark.needs_locales_compilation
    def test_custom_description_text_no_lang(self):
        addon = addon_factory(summary='Foo', description='Bar', default_locale='de')
        custom_desc_en = (
            # this is predefined in strings.jinja2 (and localized already)
            'Block invisible trackers and spying ads that follow you around the web.'
        )
        custom_desc_fr = (
            'Bloquez les traqueurs invisibles et les publicités espionnes qui vous '
            'suivent sur le Web.'
        )
        custom_desc_de = (
            'Blockieren Sie unsichtbare Verfolger und Werbung, die Sie beobachtet '
            'und im Netz verfolgt.'
        )
        item = DiscoveryItem.objects.create(
            addon=addon, custom_description=custom_desc_en
        )
        assert self.serialize(item)['description_text'] == {
            'en-US': custom_desc_en,
            'de': custom_desc_de,
        }
        with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
            assert self.serialize(item)['description_text'] == custom_desc_de

        # repeat for the edge case when we have a different system language than en-US
        with self.activate('fr'):
            item.reload()
            assert self.serialize(item)['description_text'] == {
                'en-US': custom_desc_en,
                'fr': custom_desc_fr,
                'de': custom_desc_de,
            }
            with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
                assert self.serialize(item)['description_text'] == custom_desc_fr

    @pytest.mark.needs_locales_compilation
    def test_custom_description_text_lang_specified(self):
        addon = addon_factory(summary='Foo', description='Bar', default_locale='de')
        custom_desc_en = (
            # this is predefined in strings.jinja2 (and localized already)
            'Block invisible trackers and spying ads that follow you around the web.'
        )
        custom_desc_fr = (
            'Bloquez les traqueurs invisibles et les publicités espionnes qui vous '
            'suivent sur le Web.'
        )
        custom_desc_de = (
            'Blockieren Sie unsichtbare Verfolger und Werbung, die Sie beobachtet '
            'und im Netz verfolgt.'
        )
        item = DiscoveryItem.objects.create(
            addon=addon, custom_description=custom_desc_en
        )
        # we have l10n for fr
        with self.activate('fr'):
            item.reload()
            assert self.serialize(item, 'fr')['description_text'] == {
                'fr': custom_desc_fr,
            }
            with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
                assert self.serialize(item, 'fr')['description_text'] == custom_desc_fr

        # but we don't for az
        with self.activate('az'):
            item.reload()
            assert self.serialize(item, 'az')['description_text'] == {
                'de': custom_desc_de,
                'az': None,
                '_default': 'de',
            }
            with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
                assert self.serialize(item, 'az')['description_text'] == custom_desc_de

            # cover the edge case where the addon is set a default locale we don't have
            item.addon.update(default_locale='az')
            assert self.serialize(item, 'az')['description_text'] == {
                'en-US': custom_desc_en,
                'az': None,
                '_default': 'en-US',
            }
            with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
                assert self.serialize(item, 'az')['description_text'] == custom_desc_en

    def test_description_text_empty(self):
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

    def test_no_custom_description_text_extension(self):
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

    def test_no_custom_description_text_not_extension(self):
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
