from django.utils.encoding import smart_text

import mock
import six

from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import (
    TestCase, addon_factory, collection_factory, user_factory)
from olympia.amo.urlresolvers import reverse
from olympia.legacy_discovery import views
from olympia.legacy_discovery.forms import DiscoveryModuleForm
from olympia.legacy_discovery.models import DiscoveryModule
from olympia.legacy_discovery.modules import registry
from olympia.users.models import UserProfile


class TestModuleAdmin(TestCase):

    def test_sync_db_and_registry(self):
        def check():
            views._sync_db_and_registry(qs, amo.FIREFOX.id)
            registry_len = len(registry)
            assert registry_len
            assert qs.count() == registry_len
            modules = qs.values_list('module', flat=True)
            assert set(modules) == set(registry.keys())

        qs = DiscoveryModule.objects.filter(app=amo.FIREFOX.id)
        assert qs.count() == 0

        # All our modules get added.
        check()

        # The deleted module is removed.
        with mock.patch.dict(registry):
            registry.popitem()
            check()

    def test_discovery_module_form_bad_locale(self):
        data = {
            'app': amo.FIREFOX.id,
            'module': 'xx',
            'locales': 'fake'
        }
        form = DiscoveryModuleForm(data)
        assert form.errors['locales']

    def test_discovery_module_form_dedupe(self):
        data = {
            'app': amo.FIREFOX.id,
            'module': 'xx',
            'locales': 'en-US he he fa fa'
        }
        form = DiscoveryModuleForm(data)
        assert form.is_valid()
        cleaned_locales = form.cleaned_data['locales'].split()
        assert sorted(cleaned_locales) == ['en-US', 'fa', 'he']

    def test_module_admin_is_not_redirected_to_firefox_new_page(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(reverse('discovery.module_admin'))
        assert response.status_code == 200


class TestUrls(TestCase):
    def test_redirect_to_mozilla_new_page(self):
        response = self.client.get('/en-US/firefox/discovery/', follow=False)
        self.assertRedirects(
            response,
            'https://www.mozilla.org/firefox/new/',
            status_code=301, fetch_redirect_response=False)


class TestPromos(TestCase):
    def setUp(self):
        super(TestPromos, self).setUp()
        # Create a few add-ons...
        self.addon1 = addon_factory()
        self.addon2 = addon_factory()
        self.addon3 = addon_factory(name='That & This', summary='This & That')
        # Create a user for the collection.
        self.user = UserProfile.objects.create(username='mozilla')
        games_collection = collection_factory(author=self.user, slug='games')
        games_collection.set_addons(
            [self.addon1.pk, self.addon2.pk, self.addon3.pk])
        DiscoveryModule.objects.create(
            app=amo.FIREFOX.id, ordering=1, module='Games!')

        musthave_collection = collection_factory(
            author=self.user, slug='must-have-media')
        musthave_collection.set_addons(
            [self.addon1.pk, self.addon2.pk, self.addon3.pk])
        DiscoveryModule.objects.create(
            app=amo.FIREFOX.id, ordering=2, module='Must-Have Media')

    def get_home_url(self):
        return reverse('addons.homepage_promos')

    def _test_response_contains_addons(self, response):
        assert response.status_code == 200
        assert response.content
        content = smart_text(response.content)
        assert six.text_type(self.addon1.name) in content
        assert six.text_type(self.addon2.name) in content
        assert 'This &amp; That' in content

    def test_no_params(self):
        response = self.client.get(self.get_home_url())
        assert response.status_code == 404

    def test_home_ignores_platforms(self):
        """Ensure that we get the same thing for the homepage promos regardless
        # of the platform."""
        file_ = self.addon1.current_version.all_files[0]
        file_.update(platform=amo.PLATFORM_LINUX.id)
        assert self.addon1.current_version.supported_platforms == [
            amo.PLATFORM_LINUX]

        response_mac = self.client.get(
            self.get_home_url(), {'version': '10.0', 'platform': 'mac'})
        response_darwin = self.client.get(
            self.get_home_url(), {'version': '10.0', 'platform': 'Darwin'})
        response_win = self.client.get(
            self.get_home_url(), {'version': '10.0', 'platform': 'win'})
        response_winnt = self.client.get(
            self.get_home_url(), {'version': '10.0', 'platform': 'WINNT'})

        assert response_mac.status_code == 200
        assert response_darwin.status_code == 200
        assert response_win.status_code == 200
        assert response_winnt.status_code == 200
        assert response_mac.content == response_darwin.content
        assert response_win.content == response_winnt.content
        assert response_win.content == response_mac.content
        self._test_response_contains_addons(response_win)

    def test_home_no_platform(self):
        response = self.client.get(self.get_home_url(), {'version': '10.0'})
        self._test_response_contains_addons(response)

    def test_home_no_version(self):
        response = self.client.get(self.get_home_url(), {'platform': 'lol'})
        self._test_response_contains_addons(response)

    def test_home_does_not_contain_disabled_addons(self):
        self.addon1.update(disabled_by_user=True)
        self.addon2.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.get_home_url(), {'platform': 'mac'})
        assert response.status_code == 200
        assert response.content
        content = smart_text(response.content)
        assert six.text_type(self.addon1.name) not in content
        assert six.text_type(self.addon2.name) not in content
        assert 'This &amp; That' in content

    def test_games_linkified_home(self):
        response = self.client.get(self.get_home_url(),
                                   {'version': '10.0', 'platform': 'mac'})
        self._test_response_contains_addons(response)
        doc = pq(response.content)
        h2_link = doc('h2 a').eq(0)
        expected_url = '%s%s' % (
            reverse('collections.detail', args=[self.user.id, 'games']),
            '?src=hp-dl-promo')
        assert h2_link.attr('href') == expected_url

    def test_musthave_media_linkified_home(self):
        response = self.client.get(self.get_home_url(),
                                   {'version': '10.0', 'platform': 'mac'})
        assert response.status_code == 200
        doc = pq(response.content)
        h2_link = doc('h2 a').eq(1)
        expected_url = '%s%s' % (
            reverse('collections.detail', args=[
                self.user.id, 'must-have-media']),
            '?src=hp-dl-promo')
        assert h2_link.attr('href') == expected_url

    def test_musthave_media_no_double_escaping(self):
        response = self.client.get(self.get_home_url(),
                                   {'version': '10.0', 'platform': 'mac'})
        assert response.status_code == 200

        doc = pq(response.content)
        assert 'This &amp; That' in doc.html()
        assert 'That &amp; This' in doc.html()
