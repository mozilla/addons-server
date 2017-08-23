from django.test import RequestFactory

from olympia.amo.tests import (
    addon_factory, collection_factory, TestCase, user_factory)
from olympia.addons.models import ReplacementAddon
from olympia.addons.admin import ReplacementAddonAdmin
from olympia.amo.urlresolvers import reverse
from olympia.users.models import UserProfile
from olympia.zadmin.admin import StaffAdminSite


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


class TestReplacementAddonList(TestCase):
    fixtures = ['base/users']

    def test_fields(self):
        model_admin = ReplacementAddonAdmin(ReplacementAddon, None)
        self.assertEqual(
            list(model_admin.get_list_display(None)),
            ['guid', 'path', 'guid_slug', '_url'])

    def test_list_values(self):
        ReplacementAddon.objects.create(guid='@foofoofoo', path='/addon/bar/')
        request = RequestFactory().get(
            '/en-US/admin/models/addons/replacementaddon/')
        request.user = UserProfile.objects.get(email='admin@mozilla.com')
        adminview = ReplacementAddonAdmin(
            ReplacementAddon, StaffAdminSite(name='staffadmin'))
        view = adminview.changelist_view(request)
        assert '@foofoofoo' in view.rendered_content
        assert '/addon/bar/' in view.rendered_content
        test_url = '<a href="%s">Test</a>' % (
            reverse('addons.find_replacement') + '?guid=@foofoofoo')
        assert test_url in view.rendered_content
        # guid is not on AMO so no slug to show
        assert '- Add-on not on AMO -' in view.rendered_content
        # show the slug when the add-on exists
        addon_factory(guid='@foofoofoo', slug='slugmcslugface')
        view = adminview.changelist_view(request)
        assert 'slugmcslugface' in view.rendered_content
