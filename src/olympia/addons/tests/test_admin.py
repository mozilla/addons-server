from django.conf import settings
from django.contrib import admin

from olympia.addons.admin import ReplacementAddonAdmin
from olympia.addons.models import ReplacementAddon
from olympia.amo.tests import (
    TestCase, addon_factory, collection_factory, user_factory)
from olympia.amo.urlresolvers import django_reverse, reverse


class TestReplacementAddonForm(TestCase):
    def test_valid_addon(self):
        addon_factory(slug='bar')
        form = ReplacementAddonAdmin(
            ReplacementAddon, admin.site).get_form(None)(
                {'guid': 'foo', 'path': '/addon/bar/'})
        assert form.is_valid(), form.errors
        assert form.cleaned_data['path'] == '/addon/bar/'

    def test_invalid(self):
        form = ReplacementAddonAdmin(
            ReplacementAddon, admin.site).get_form(None)(
                {'guid': 'foo', 'path': '/invalid_url/'})
        assert not form.is_valid()

    def test_valid_collection(self):
        bagpuss = user_factory(username='bagpuss')
        collection_factory(slug='stuff', author=bagpuss)
        form = ReplacementAddonAdmin(
            ReplacementAddon, admin.site).get_form(None)(
                {'guid': 'foo', 'path': '/collections/bagpuss/stuff/'})
        assert form.is_valid(), form.errors
        assert form.cleaned_data['path'] == '/collections/bagpuss/stuff/'

    def test_url(self):
        form = ReplacementAddonAdmin(
            ReplacementAddon, admin.site).get_form(None)(
                {'guid': 'foo', 'path': 'https://google.com/'})
        assert form.is_valid()
        assert form.cleaned_data['path'] == 'https://google.com/'

    def test_invalid_urls(self):
        assert not ReplacementAddonAdmin(
            ReplacementAddon, admin.site).get_form(None)(
                {'guid': 'foo', 'path': 'ftp://google.com/'}).is_valid()
        assert not ReplacementAddonAdmin(
            ReplacementAddon, admin.site).get_form(None)(
                {'guid': 'foo', 'path': 'https://88999@~'}).is_valid()
        assert not ReplacementAddonAdmin(
            ReplacementAddon, admin.site).get_form(None)(
                {'guid': 'foo', 'path': 'https://www. rutrt/'}).is_valid()

        path = '/addon/bar/'
        site = settings.SITE_URL
        full_url = site + path
        # path is okay
        assert ReplacementAddonAdmin(
            ReplacementAddon, admin.site).get_form(None)(
                {'guid': 'foo', 'path': path}).is_valid()
        # but we don't allow full urls for AMO paths
        form = ReplacementAddonAdmin(
            ReplacementAddon, admin.site).get_form(None)(
                {'guid': 'foo', 'path': full_url})
        assert not form.is_valid()
        assert ('Paths for [%s] should be relative, not full URLs including '
                'the domain name' % site in form.errors['path'])


class TestAddonAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:addons_addon_changelist')

    def test_can_see_addon_module_in_admin_with_addons_edit(self):
        pass

    def test_can_list_with_addons_edit_permission(self):
        addon = addon_factory()
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')

    def test_can_edit_with_addons_edit_permission(self):
        addon = addon_factory(guid='@foo')
        self.detail_url = reverse(
            'admin:addons_addon_change', args=(addon.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')

        post_data = {
            # Django wants the whole form to be submitted, unfortunately.
            'total_ratings': addon.total_ratings,
            'text_ratings_count': addon.text_ratings_count,
            'default_locale': addon.default_locale,
            'weekly_downloads': addon.weekly_downloads,
            'total_downloads': addon.total_downloads,
            'average_rating': addon.average_rating,
            'average_daily_users': addon.average_daily_users,
            'bayesian_rating': addon.bayesian_rating,
            'reputation': addon.reputation,
            'type': addon.type,
            'slug': addon.slug
        }
        post_data['guid'] = '@bar'
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        addon.reload()
        assert addon.guid == '@bar'

    def test_can_not_list_without_addons_edit_permission(self):
        addon = addon_factory()
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 403
        assert addon.guid not in response.content.decode('utf-8')

    def test_can_not_edit_without_addons_edit_permission(self):
        addon = addon_factory(guid='@foo')
        self.detail_url = reverse(
            'admin:addons_addon_change', args=(addon.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 403
        assert addon.guid not in response.content.decode('utf-8')

        post_data = {
            # Django wants the whole form to be submitted, unfortunately.
            'total_ratings': addon.total_ratings,
            'text_ratings_count': addon.text_ratings_count,
            'default_locale': addon.default_locale,
            'weekly_downloads': addon.weekly_downloads,
            'total_downloads': addon.total_downloads,
            'average_rating': addon.average_rating,
            'average_daily_users': addon.average_daily_users,
            'bayesian_rating': addon.bayesian_rating,
            'type': addon.type,
            'slug': addon.slug
        }
        post_data['guid'] = '@bar'
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 403
        addon.reload()
        assert addon.guid == '@foo'


class TestReplacementAddonList(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:addons_replacementaddon_changelist')

    def test_fields(self):
        model_admin = ReplacementAddonAdmin(ReplacementAddon, admin.site)
        self.assertEqual(
            list(model_admin.get_list_display(None)),
            ['guid', 'path', 'guid_slug', '_url'])

    def test_can_see_replacementaddon_module_in_admin_with_addons_edit(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        # Use django's reverse, since that's what the admin will use. Using our
        # own would fail the assertion because of the locale that gets added.
        self.list_url = django_reverse(
            'admin:addons_replacementaddon_changelist')
        assert self.list_url in response.content.decode('utf-8')

    def test_can_see_replacementaddon_module_in_admin_with_admin_curate(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        # Use django's reverse, since that's what the admin will use. Using our
        # own would fail the assertion because of the locale that gets added.
        self.list_url = django_reverse(
            'admin:addons_replacementaddon_changelist')
        assert self.list_url in response.content.decode('utf-8')

    def test_can_list_with_addons_edit_permission(self):
        ReplacementAddon.objects.create(
            guid='@bar', path='/addon/bar-replacement/')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert '/addon/bar-replacement/' in response.content

    def test_can_not_edit_with_addons_edit_permission(self):
        replacement = ReplacementAddon.objects.create(
            guid='@bar', path='/addon/bar-replacement/')
        self.detail_url = reverse(
            'admin:addons_replacementaddon_change', args=(replacement.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(
            self.detail_url, {'guid': '@bar', 'path': replacement.path},
            follow=True)
        assert response.status_code == 403

    def test_can_not_delete_with_addons_edit_permission(self):
        replacement = ReplacementAddon.objects.create(
            guid='@foo', path='/addon/foo-replacement/')
        self.delete_url = reverse(
            'admin:addons_replacementaddon_delete', args=(replacement.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(
            self.delete_url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 403
        assert ReplacementAddon.objects.filter(pk=replacement.pk).exists()

    def test_can_edit_with_admin_curation_permission(self):
        replacement = ReplacementAddon.objects.create(
            guid='@foo', path='/addon/foo-replacement/')
        self.detail_url = reverse(
            'admin:addons_replacementaddon_change', args=(replacement.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert '/addon/foo-replacement/' in response.content

        response = self.client.post(
            self.detail_url, {'guid': '@bar', 'path': replacement.path},
            follow=True)
        assert response.status_code == 200
        replacement.reload()
        assert replacement.guid == '@bar'

    def test_can_delete_with_admin_curation_permission(self):
        replacement = ReplacementAddon.objects.create(
            guid='@foo', path='/addon/foo-replacement/')
        self.delete_url = reverse(
            'admin:addons_replacementaddon_delete', args=(replacement.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 200
        response = self.client.post(
            self.delete_url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 200
        assert not ReplacementAddon.objects.filter(pk=replacement.pk).exists()

    def test_can_list_with_admin_curation_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        # '@foofoo&foo' isn't a valid guid, because &, but testing urlencoding.
        ReplacementAddon.objects.create(guid='@foofoo&foo', path='/addon/bar/')

        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert '@foofoo&amp;foo' in response.content
        assert '/addon/bar/' in response.content
        test_url = str('<a href="%s">Test</a>' % (
            reverse('addons.find_replacement') + '?guid=%40foofoo%26foo'))
        assert test_url in response.content, response.content

        # guid is not on AMO so no slug to show
        assert '- Add-on not on AMO -' in response.content
        # show the slug when the add-on exists
        addon_factory(guid='@foofoo&foo', slug='slugymcslugface')
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert 'slugymcslugface' in response.content
