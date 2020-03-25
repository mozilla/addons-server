from pyquery import PyQuery as pq

from django.conf import settings
from django.contrib import admin

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.admin import ReplacementAddonAdmin
from olympia.addons.models import ReplacementAddon
from olympia.amo.tests import (
    TestCase, addon_factory, collection_factory, user_factory, version_factory)
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
        self.admin_home_url = reverse('admin:index')
        self.list_url = reverse('admin:addons_addon_changelist')

    def test_can_see_addon_module_in_admin_with_addons_edit(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert modules == ['Addons']

    def test_can_not_see_addon_module_in_admin_without_permissions(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert modules == []

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
            'slug': addon.slug,
            'status': addon.status,
        }
        post_data['guid'] = '@bar'
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        addon.reload()
        assert addon.guid == '@bar'

    def test_show_link_to_reviewer_tools_listed(self):
        addon = addon_factory(guid='@foo')
        version_factory(addon=addon, channel=amo.RELEASE_CHANNEL_LISTED)
        detail_url = reverse('admin:addons_addon_change', args=(addon.pk,))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert b'Reviewer Tools (listed)' in response.content
        assert b'Reviewer Tools (unlisted)' not in response.content

    def test_show_link_to_reviewer_tools_unlisted(self):
        version_kw = {'channel': amo.RELEASE_CHANNEL_UNLISTED}
        addon = addon_factory(guid='@foo', version_kw=version_kw)
        detail_url = reverse('admin:addons_addon_change', args=(addon.pk,))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert b'Reviewer Tools (listed)' not in response.content
        assert b'Reviewer Tools (unlisted)' in response.content

    def test_show_links_to_reviewer_tools_with_both_channels(self):
        addon = addon_factory(guid='@foo')
        version_factory(addon=addon, channel=amo.RELEASE_CHANNEL_LISTED)
        version_factory(addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        detail_url = reverse('admin:addons_addon_change', args=(addon.pk,))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        content = response.content.decode('utf-8')
        assert 'Reviewer Tools (listed)' in content
        assert ('http://testserver{}'.format(
            reverse('reviewers.review', args=('listed', addon.pk))
        ) in content)
        assert 'Reviewer Tools (unlisted)' in content
        assert ('http://testserver{}'.format(
            reverse('reviewers.review', args=('unlisted', addon.pk))
        ) in content)

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
            'slug': addon.slug,
            'status': addon.status,
        }
        post_data['guid'] = '@bar'
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 403
        addon.reload()
        assert addon.guid == '@foo'

    def test_access_using_slug(self):
        addon = addon_factory(guid='@foo')
        detail_url_by_slug = reverse(
            'admin:addons_addon_change', args=(addon.slug,)
        )
        detail_url_final = reverse(
            'admin:addons_addon_change', args=(addon.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(detail_url_by_slug, follow=False)
        self.assert3xx(response, detail_url_final, 301)

    def test_access_using_guid(self):
        addon = addon_factory(guid='@foo')
        detail_url_by_guid = reverse(
            'admin:addons_addon_change', args=(addon.guid,)
        )
        detail_url_final = reverse(
            'admin:addons_addon_change', args=(addon.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(detail_url_by_guid, follow=True)
        self.assert3xx(response, detail_url_final, 301)

    def test_can_edit_deleted_addon(self):
        addon = addon_factory(guid='@foo')
        addon.delete()
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

    def _get_full_post_data(self, addon, addonuser):
        return {
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
            'slug': addon.slug,
            'status': addon.status,
            'guid': addon.guid,
            'addonuser_set-TOTAL_FORMS': 1,
            'addonuser_set-INITIAL_FORMS': 1,
            'addonuser_set-MIN_NUM_FORMS': 0,
            'addonuser_set-MAX_NUM_FORMS': 1000,
            'addonuser_set-0-id': addonuser.pk,
            'addonuser_set-0-addon': addon.pk,
            'addonuser_set-0-user': addonuser.user.pk,
            'addonuser_set-0-role': amo.AUTHOR_ROLE_OWNER,
            'addonuser_set-0-listed': 'on',
            'addonuser_set-0-position': 0,

            'files-TOTAL_FORMS': 1,
            'files-INITIAL_FORMS': 1,
            'files-MIN_NUM_FORMS': 0,
            'files-MAX_NUM_FORMS': 0,
            'files-0-id': addon.current_version.all_files[0].pk,
            'files-0-status': addon.current_version.all_files[0].status,
        }

    def test_can_edit_addonuser_and_files_if_has_admin_advanced(self):
        addon = addon_factory(guid='@foo', users=[user_factory()])
        file = addon.current_version.all_files[0]
        addonuser = addon.addonuser_set.get()
        self.detail_url = reverse(
            'admin:addons_addon_change', args=(addon.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')
        post_data = self._get_full_post_data(addon, addonuser)
        post_data.update(**{
            'guid': '@bar',  # update it.
            'addonuser_set-0-user': user.pk,  # Different user than initial.
            'files-0-status': amo.STATUS_AWAITING_REVIEW,  # Different status.
        })
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        addon.reload()
        assert addon.guid == '@bar'
        addonuser.reload()
        assert addonuser.user == user
        file.reload()
        assert file.status == amo.STATUS_AWAITING_REVIEW

    def test_can_not_edit_addonuser_files_if_doesnt_have_admin_advanced(self):
        addon = addon_factory(guid='@foo', users=[user_factory()])
        file = addon.current_version.all_files[0]
        addonuser = addon.addonuser_set.get()
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

        post_data = self._get_full_post_data(addon, addonuser)
        post_data.update(**{
            'guid': '@bar',  # update it.
            'addonuser_set-0-user': user.pk,  # Different user than initial.
            'files-0-status': amo.STATUS_AWAITING_REVIEW,  # Different status.
        })
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        addon.reload()
        assert addon.guid == '@bar'
        addonuser.reload()
        assert addonuser.user != user
        file.reload()
        assert file.status != amo.STATUS_AWAITING_REVIEW

    def test_can_manage_unlisted_versions_and_change_addon_status(self):
        addon = addon_factory(guid='@foo', users=[user_factory()])
        unlisted_version = version_factory(
            addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        listed_version = addon.current_version
        addonuser = addon.addonuser_set.get()
        self.detail_url = reverse(
            'admin:addons_addon_change', args=(addon.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')
        doc = pq(response.content)
        assert doc('#id_files-0-id').attr('value') == str(
            unlisted_version.all_files[0].id)
        assert doc('#id_files-1-id').attr('value') == str(
            addon.current_version.all_files[0].id)

        # pagination links aren't shown for less than page size (30) files.
        next_url = self.detail_url + '?page=2'
        assert next_url not in response.content.decode('utf-8')

        post_data = self._get_full_post_data(addon, addonuser)
        post_data.update(**{
            'status': amo.STATUS_DISABLED,
            'files-TOTAL_FORMS': 2,
            'files-INITIAL_FORMS': 2,
            'files-0-id': unlisted_version.all_files[0].pk,
            'files-0-status': amo.STATUS_DISABLED,
            'files-1-id': listed_version.all_files[0].pk,
            'files-1-status': amo.STATUS_AWAITING_REVIEW,  # Different status.
        })
        # Confirm the original statuses so we know they're actually changing.
        assert addon.status != amo.STATUS_DISABLED
        assert listed_version.all_files[0].status != amo.STATUS_AWAITING_REVIEW
        assert unlisted_version.all_files[0].status != amo.STATUS_DISABLED

        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        addon.reload()
        assert addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.filter(
            action=amo.LOG.CHANGE_STATUS.id).exists()
        listed_version = addon.versions.get(id=listed_version.id)
        assert listed_version.all_files[0].status == amo.STATUS_AWAITING_REVIEW
        unlisted_version = addon.versions.get(id=unlisted_version.id)
        assert unlisted_version.all_files[0].status == amo.STATUS_DISABLED

    def test_status_cannot_change_for_deleted_version(self):
        addon = addon_factory(guid='@foo', users=[user_factory()])
        file = addon.current_version.all_files[0]
        self.detail_url = reverse(
            'admin:addons_addon_change', args=(addon.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.grant_permission(user, 'Admin:Advanced')
        post_data = self._get_full_post_data(addon, addon.addonuser_set.get())
        file.version.delete()

        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert f'{file.version} - Deleted' in response.content.decode('utf-8')
        assert 'disabled' in (
            pq(response.content)('#id_files-0-status')[0].attrib)
        post_data.update(**{
            'files-0-status': amo.STATUS_AWAITING_REVIEW,  # Different status.
        })
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        file.reload()
        assert file.status != amo.STATUS_AWAITING_REVIEW

    def test_query_count(self):
        addon = addon_factory(guid='@foo', users=[user_factory()])
        user = user_factory()
        self.detail_url = reverse(
            'admin:addons_addon_change', args=(addon.pk,))
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        with self.assertNumQueries(24):
            # It's very high because most of AddonAdmin is unoptimized but we
            # don't want it unexpectedly increasing.
            response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')

        version_factory(addon=addon)
        with self.assertNumQueries(24):
            # confirm it scales
            response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')

    def test_version_pagination(self):
        addon = addon_factory(users=[user_factory()])
        first_file = addon.current_version.all_files[0]
        [version_factory(addon=addon) for i in range(0, 30)]
        user = user_factory()
        self.detail_url = reverse(
            'admin:addons_addon_change', args=(addon.pk,))
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')
        assert len(pq(response.content)('.field-version__version')) == 30
        next_url = self.detail_url + '?page=2'
        assert next_url in response.content.decode('utf-8')
        response = self.client.get(next_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')
        assert len(pq(response.content)('.field-version__version')) == 1
        assert pq(response.content)('#id_files-0-id')[0].attrib['value'] == (
            str(first_file.id))


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
        assert '/addon/bar-replacement/' in response.content.decode('utf-8')

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
        assert '/addon/foo-replacement/' in response.content.decode('utf-8')

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
        assert '@foofoo&amp;foo' in response.content.decode('utf-8')
        assert '/addon/bar/' in response.content.decode('utf-8')
        test_url = str('<a href="%s">Test</a>' % (
            reverse('addons.find_replacement') + '?guid=%40foofoo%26foo'))
        assert test_url in response.content.decode('utf-8')
        # guid is not on AMO so no slug to show
        assert '- Add-on not on AMO -' in response.content.decode('utf-8')
        # show the slug when the add-on exists
        addon_factory(guid='@foofoo&foo', slug='slugymcslugface')
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert 'slugymcslugface' in response.content.decode('utf-8')
