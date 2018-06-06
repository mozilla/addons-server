from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage import (
    default_storage as default_messages_storage)
from django.test import RequestFactory
from django.utils.dateformat import DateFormat

import mock

from pyquery import PyQuery as pq


from olympia import amo, core
from olympia.abuse.models import AbuseReport
from olympia.activity.models import ActivityLog
from olympia.amo.tests import (
    addon_factory, TestCase, user_factory, version_factory)
from olympia.amo.urlresolvers import reverse
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating
from olympia.users.admin import UserAdmin
from olympia.users.models import UserProfile


class TestUserAdmin(TestCase):
    def setUp(self):
        self.user = user_factory()
        self.list_url = reverse('admin:users_userprofile_changelist')
        self.detail_url = reverse(
            'admin:users_userprofile_change', args=(self.user.pk,)
        )
        self.delete_url = reverse(
            'admin:users_userprofile_delete', args=(self.user.pk, )
        )

    def test_can_not_edit_without_users_edit_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(
            self.detail_url, {'username': 'foo', 'email': self.user.email},
            follow=True)
        assert response.status_code == 403
        assert self.user.reload().username != 'foo'

    def test_can_edit_with_users_edit_permission(self):
        old_username = self.user.username
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Users:Edit')
        self.client.login(email=user.email)
        core.set_user(user)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        response = self.client.post(
            self.detail_url, {'username': 'foo', 'email': self.user.email},
            follow=True)
        assert response.status_code == 200
        assert self.user.reload().username == 'foo'
        alog = ActivityLog.objects.latest('pk')
        assert alog.action == amo.LOG.ADMIN_USER_EDITED.id
        assert alog.arguments == [self.user]
        assert alog.details == {'username': [old_username, 'foo']}

    @mock.patch.object(UserProfile, 'delete_or_disable_related_content')
    def test_can_not_delete_with_users_edit_permission(
            self, delete_or_disable_related_content_mock):
        user = user_factory()
        assert not user.deleted
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Users:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(self.delete_url, {'post': 'yes'},
                                    follow=True)
        assert response.status_code == 403
        user.reload()
        assert not user.deleted
        assert user.email
        assert delete_or_disable_related_content_mock.call_count == 0

    @mock.patch.object(UserProfile, 'delete_or_disable_related_content')
    def test_can_delete_with_admin_advanced_permission(
            self, delete_or_disable_related_content_mock):
        user = user_factory()
        assert not self.user.deleted
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        core.set_user(user)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 200
        response = self.client.post(self.delete_url, {'post': 'yes'},
                                    follow=True)
        assert response.status_code == 200
        self.user.reload()
        assert self.user.deleted
        assert self.user.email is None
        assert delete_or_disable_related_content_mock.call_count == 1
        assert (
            delete_or_disable_related_content_mock.call_args[1] ==
            {'delete': True})
        alog = ActivityLog.objects.latest('pk')
        assert alog.action == amo.LOG.ADMIN_USER_ANONYMIZED.id
        assert alog.arguments == [self.user]

    def test_get_actions(self):
        user_admin = UserAdmin(UserProfile, admin.site)
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        user_admin.get_actions(request) == []

        request.user = user_factory()
        self.grant_permission(request.user, 'Users:Edit')
        user_admin.get_actions(request) == ['ban_action']

    def test_ban_action(self):
        another_user = user_factory()
        a_third_user = user_factory()
        users = UserProfile.objects.filter(
            pk__in=(another_user.pk, self.user.pk))
        user_admin = UserAdmin(UserProfile, admin.site)
        request = RequestFactory().get('/')
        request.user = user_factory()
        core.set_user(request.user)
        request._messages = default_messages_storage(request)
        user_admin.ban_action(request, users)
        # Both users should be banned.
        another_user.reload()
        self.user.reload()
        assert another_user.deleted
        assert another_user.email
        assert self.user.deleted
        assert self.user.email
        # The 3rd user should be unaffected.
        assert not a_third_user.reload().deleted

        # We should see 2 activity logs for banning.
        assert ActivityLog.objects.filter(
            action=amo.LOG.ADMIN_USER_BANNED.id).count() == 2

    def test_ban_button_in_change_view(self):
        ban_url = reverse('admin:users_userprofile_ban', args=(self.user.pk, ))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Users:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert ban_url in response.content.decode('utf-8')

    def test_delete_picture_button_in_change_view(self):
        delete_picture_url = reverse('admin:users_userprofile_delete_picture',
                                     args=(self.user.pk, ))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Users:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert delete_picture_url in response.content.decode('utf-8')

    def test_ban(self):
        ban_url = reverse('admin:users_userprofile_ban', args=(self.user.pk, ))
        wrong_ban_url = reverse(
            'admin:users_userprofile_ban', args=(self.user.pk + 42, ))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        core.set_user(user)
        response = self.client.post(ban_url, follow=True)
        assert response.status_code == 403
        self.grant_permission(user, 'Users:Edit')
        response = self.client.get(ban_url, follow=True)
        assert response.status_code == 405  # Wrong http method.
        response = self.client.post(wrong_ban_url, follow=True)
        assert response.status_code == 404  # Wrong pk.

        self.user.reload()
        assert not self.user.deleted

        response = self.client.post(ban_url, follow=True)
        assert response.status_code == 200
        assert response.redirect_chain[0][0].endswith(self.detail_url)
        assert response.redirect_chain[0][1] == 302
        self.user.reload()
        assert self.user.deleted
        assert self.user.email
        alog = ActivityLog.objects.latest('pk')
        assert alog.action == amo.LOG.ADMIN_USER_BANNED.id
        assert alog.arguments == [self.user]

    @mock.patch.object(UserProfile, 'delete_picture')
    def test_delete_picture(self, delete_picture_mock):
        delete_picture_url = reverse(
            'admin:users_userprofile_delete_picture', args=(self.user.pk, ))
        wrong_delete_picture_url = reverse(
            'admin:users_userprofile_delete_picture',
            args=(self.user.pk + 42, ))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        core.set_user(user)
        response = self.client.post(delete_picture_url, follow=True)
        assert response.status_code == 403
        self.grant_permission(user, 'Users:Edit')
        response = self.client.get(delete_picture_url, follow=True)
        assert response.status_code == 405  # Wrong http method.
        response = self.client.post(wrong_delete_picture_url, follow=True)
        assert response.status_code == 404  # Wrong pk.

        assert delete_picture_mock.call_count == 0

        response = self.client.post(delete_picture_url, follow=True)
        assert response.status_code == 200
        assert response.redirect_chain[0][0].endswith(self.detail_url)
        assert response.redirect_chain[0][1] == 302

        assert delete_picture_mock.call_count == 1

        alog = ActivityLog.objects.latest('pk')
        assert alog.action == amo.LOG.ADMIN_USER_PICTURE_DELETED.id
        assert alog.arguments == [self.user]

    def test_picture_img(self):
        model_admin = UserAdmin(UserProfile, admin.site)
        assert self.user.picture_url.endswith('anon_user.png')
        assert (
            model_admin.picture_img(self.user) ==
            '<img src="%s" />' % self.user.picture_url)

        self.user.update(picture_type='image/png')
        assert (
            model_admin.picture_img(self.user) ==
            '<img src="%s" />' % self.user.picture_url)

    def test_known_ip_adresses(self):
        self.user.update(last_login_ip='127.1.2.3')
        Rating.objects.create(
            addon=addon_factory(), user=self.user, ip_address='127.1.2.3')
        dummy_addon = addon_factory()
        Rating.objects.create(
            addon=dummy_addon, version=dummy_addon.current_version,
            user=self.user, ip_address='128.1.2.3')
        Rating.objects.create(
            addon=dummy_addon, version=version_factory(addon=dummy_addon),
            user=self.user, ip_address='129.1.2.4')
        Rating.objects.create(
            addon=addon_factory(), user=self.user, ip_address='130.1.2.4')
        Rating.objects.create(
            addon=addon_factory(), user=self.user, ip_address='130.1.2.4')
        Rating.objects.create(
            addon=dummy_addon,
            user=user_factory(), ip_address='255.255.0.0')
        model_admin = UserAdmin(UserProfile, admin.site)
        doc = pq(model_admin.known_ip_adresses(self.user))
        result = doc('ul li').text().split()
        assert len(result) == 4
        assert (set(result) ==
                set(['130.1.2.4', '128.1.2.3', '129.1.2.4', '127.1.2.3']))

    def test_last_known_activity_time(self):
        someone_else = user_factory(username='someone_else')
        addon = addon_factory()

        model_admin = UserAdmin(UserProfile, admin.site)
        assert unicode(model_admin.last_known_activity_time(self.user)) == ''

        # Add various activities. They will be attached to whatever user is
        # set in the thread global at the time, so set that in advance.
        core.set_user(self.user)
        expected_date = self.days_ago(1)
        activity = ActivityLog.create(amo.LOG.CREATE_ADDON, addon)
        activity.update(created=self.days_ago(2))
        activity.userlog_set.update(created=self.days_ago(2))

        activity = ActivityLog.create(amo.LOG.EDIT_PROPERTIES, addon)
        activity.update(created=expected_date)
        activity.userlog_set.update(created=expected_date)

        assert activity.reload().created == expected_date

        # Create another activity, more recent, attached to a different user.
        core.set_user(someone_else)
        activity = ActivityLog.create(amo.LOG.EDIT_PROPERTIES, addon)

        expected_result = DateFormat(expected_date).format(
            settings.DATETIME_FORMAT)

        assert (unicode(model_admin.last_known_activity_time(self.user)) ==
                expected_result)

    def _call_related_content_method(self, method):
        model_admin = UserAdmin(UserProfile, admin.site)
        result = getattr(model_admin, method)(self.user)
        link = pq(result)('a')[0]
        return link.attrib['href'], link.text

    def test_collections_created(self):
        Collection.objects.create()
        Collection.objects.create(author=self.user)
        Collection.objects.create(author=self.user, listed=False)
        url, text = self._call_related_content_method('collections_created')
        expected_url = (
            reverse('admin:bandwagon_collection_changelist') +
            '?author=%d' % self.user.pk)
        assert url == expected_url
        assert text == '2'

    def test_addons_created(self):
        addon_factory()
        another_user = user_factory()
        addon_factory(users=[self.user, another_user])
        addon_factory(users=[self.user], status=amo.STATUS_PENDING)
        addon_factory(users=[self.user], status=amo.STATUS_DELETED)
        addon_factory(users=[self.user],
                      version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        url, text = self._call_related_content_method('addons_created')
        expected_url = (
            reverse('admin:addons_addon_changelist') +
            '?authors=%d' % self.user.pk)
        assert url == expected_url
        assert text == '4'

    def test_ratings_created(self):
        Rating.objects.create(addon=addon_factory(), user=self.user)
        dummy_addon = addon_factory()
        Rating.objects.create(
            addon=dummy_addon, version=dummy_addon.current_version,
            user=self.user)
        Rating.objects.create(
            addon=dummy_addon, version=version_factory(addon=dummy_addon),
            user=self.user)
        Rating.objects.create(
            addon=dummy_addon,
            user=user_factory(), ip_address='255.255.0.0')
        url, text = self._call_related_content_method('ratings_created')
        expected_url = (
            reverse('admin:ratings_rating_changelist') +
            '?user=%d' % self.user.pk)
        assert url == expected_url
        assert text == '3'

    def test_activity(self):
        addon = addon_factory()
        core.set_user(self.user)
        ActivityLog.create(amo.LOG.CREATE_ADDON, addon)
        ActivityLog.create(amo.LOG.EDIT_PROPERTIES, addon)

        # Create another activity attached to a different user.
        someone_else = user_factory()
        core.set_user(someone_else)
        ActivityLog.create(amo.LOG.EDIT_PROPERTIES, addon)
        url, text = self._call_related_content_method('activity')
        expected_url = (
            reverse('admin:activity_activitylog_changelist') +
            '?user=%d' % self.user.pk)
        assert url == expected_url
        assert text == '2'

    def test_abuse_reports_by_this_user(self):
        addon = addon_factory()
        AbuseReport.objects.create(user=self.user)
        AbuseReport.objects.create(user=self.user)
        AbuseReport.objects.create(addon=addon)
        AbuseReport.objects.create(addon=addon, reporter=self.user)
        AbuseReport.objects.create(user=user_factory(), reporter=self.user)

        url, text = self._call_related_content_method(
            'abuse_reports_by_this_user')
        expected_url = (
            reverse('admin:abuse_abusereport_changelist') +
            '?reporter=%d' % self.user.pk)
        assert url == expected_url
        assert text == '2'

    def test_abuse_reports_for_this_user(self):
        other_user = user_factory()
        addon = addon_factory()
        AbuseReport.objects.create(user=self.user)
        AbuseReport.objects.create(user=other_user)
        AbuseReport.objects.create(user=other_user, reporter=self.user)
        AbuseReport.objects.create(addon=addon, reporter=self.user)
        AbuseReport.objects.create(user=self.user, reporter=user_factory())

        url, text = self._call_related_content_method(
            'abuse_reports_for_this_user')
        expected_url = (
            reverse('admin:abuse_abusereport_changelist') +
            '?user=%d' % self.user.pk)
        assert url == expected_url
        assert text == '2'
