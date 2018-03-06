from django.conf import settings
from django.test import RequestFactory

from olympia.addons.admin import ReplacementAddonAdmin
from olympia.addons.models import ReplacementAddon
from olympia.amo.tests import (
    TestCase, addon_factory, collection_factory, user_factory)
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

    def test_url(self):
        form = ReplacementAddonAdmin(ReplacementAddon, None).get_form(None)(
            {'guid': 'foo', 'path': 'https://google.com/'})
        assert form.is_valid()

    def test_invalid_urls(self):
        assert not ReplacementAddonAdmin(ReplacementAddon, None).get_form(
            None)({'guid': 'foo', 'path': 'ftp://google.com/'}).is_valid()
        assert not ReplacementAddonAdmin(ReplacementAddon, None).get_form(
            None)({'guid': 'foo', 'path': 'https://88999@~'}).is_valid()
        assert not ReplacementAddonAdmin(ReplacementAddon, None).get_form(
            None)({'guid': 'foo', 'path': 'https://www. rutrt/'}).is_valid()

        path = '/addon/bar/'
        site = settings.SITE_URL
        full_url = site + path
        # path is okay
        assert ReplacementAddonAdmin(ReplacementAddon, None).get_form(
            None)({'guid': 'foo', 'path': path}).is_valid()
        # but we don't allow full urls for AMO paths
        form = ReplacementAddonAdmin(ReplacementAddon, None).get_form(
            None)({'guid': 'foo', 'path': full_url})
        assert not form.is_valid()
        assert ('Paths for [%s] should be relative, not full URLs including '
                'the domain name' % site in form.errors['__all__'])


class TestReplacementAddonList(TestCase):
    fixtures = ['base/users']

    def test_fields(self):
        model_admin = ReplacementAddonAdmin(ReplacementAddon, None)
        self.assertEqual(
            list(model_admin.get_list_display(None)),
            ['guid', 'path', 'guid_slug', '_url'])

    def test_list_values(self):
        # '@foofoo&foo' isn't a valid guid, because &, but testing urlencoding.
        ReplacementAddon.objects.create(guid='@foofoo&foo', path='/addon/bar/')
        request = RequestFactory().get(
            '/en-US/admin/models/addons/replacementaddon/')
        request.user = UserProfile.objects.get(email='admin@mozilla.com')
        request.session = {}
        adminview = ReplacementAddonAdmin(
            ReplacementAddon, StaffAdminSite(name='staffadmin'))
        view = adminview.changelist_view(request)
        assert '@foofoo&amp;foo' in view.rendered_content
        assert '/addon/bar/' in view.rendered_content
        test_url = '<a href="%s">Test</a>' % (
            reverse('addons.find_replacement') + '?guid=%40foofoo%26foo')
        assert test_url in view.rendered_content, view.rendered_content
        # guid is not on AMO so no slug to show
        assert '- Add-on not on AMO -' in view.rendered_content
        # show the slug when the add-on exists
        addon_factory(guid='@foofoo&foo', slug='slugymcslugface')
        view = adminview.changelist_view(request)
        assert 'slugymcslugface' in view.rendered_content
