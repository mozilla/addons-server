from olympia.amo.tests import (
    addon_factory, collection_factory, TestCase, user_factory)
from olympia.addons.models import ReplacementAddon
from olympia.addons.admin import ReplacementAddonAdmin


class TestReplacementAddonForm(TestCase):
    def test_valid_addon(self):
        addon_factory(slug='bar')
        form = ReplacementAddonAdmin(ReplacementAddon, None).get_form(None)(
            {'guid': 'foo', 'path': '/addon/bar/'})
        assert form.is_valid(), form.errors

    def test_invalid(self):
        form = ReplacementAddonAdmin(ReplacementAddon, None).get_form(None)(
            {'guid': 'foo', 'path': '/invalid_url/'})
        assert not form.is_valid()

    def test_valid_collection(self):
        bagpuss = user_factory(username='bagpuss')
        collection_factory(slug='stuff', author=bagpuss)
        form = ReplacementAddonAdmin(ReplacementAddon, None).get_form(None)(
            {'guid': 'foo', 'path': '/collections/bagpuss/stuff/'})
        assert form.is_valid(), form.errors
