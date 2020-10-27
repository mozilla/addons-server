from olympia import amo
from olympia.amo.tests import addon_factory, TestCase
from olympia.discovery.models import DiscoveryItem


class TestDiscoveryItem(TestCase):

    def test_description_text_custom(self):
        addon = addon_factory(summary='Foo', description='Bar')
        item = DiscoveryItem.objects.create(
            addon=addon, custom_description='Custôm Desc.')
        assert item.description_text == 'Custôm Desc.'

    def test_description_text_non_custom_extension(self):
        addon = addon_factory(summary='')
        item = DiscoveryItem.objects.create(addon=addon)
        assert item.description_text == ''

        addon.summary = 'Mÿ Summary'
        assert item.description_text == 'Mÿ Summary'

    def test_description_text_non_custom_fallback(self):
        item = DiscoveryItem.objects.create(addon=addon_factory(
            type=amo.ADDON_DICT))
        assert item.description_text == ''
