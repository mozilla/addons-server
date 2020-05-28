from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage import (
    default_storage as default_messages_storage)
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils.dateformat import DateFormat

from unittest import mock

from pyquery import PyQuery as pq

from olympia import amo, core
from olympia.abuse.models import AbuseReport
from olympia.activity.models import ActivityLog
from olympia.addons.models import AddonUser
from olympia.amo.tests import (
    addon_factory, collection_factory, TestCase, user_factory, version_factory)
from olympia.amo.urlresolvers import reverse
from olympia.api.models import APIKey, APIKeyConfirmation
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating
from olympia.reviewers.models import ReviewerScore
from olympia.users.admin import UserAdmin
from olympia.users.models import (
    EmailUserRestriction,
    IPNetworkUserRestriction,
    UserProfile
)


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

    def test_search_for_multiple_users(self):
        user = user_factory()
        another_user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Users:Edit')
        self.client.login(email=user.email)
        response = self.client.get(
            self.list_url,
            {'q': '%s,%s,foobaa' % (self.user.pk, another_user.pk)},
            follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert str(self.user.pk) in doc('#result_list').text()
        assert str(another_user.pk) in doc('#result_list').text()

    def test_search_for_multiple_user_ids(self):
        """Test the optimization when just searching for matching ids."""
        user = user_factory()
        another_user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Users:Edit')
        self.client.login(email=user.email)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(
                self.list_url,
                {'q': '%s,%s' % (self.user.pk, another_user.pk)},
                follow=True)
            queries_str = '; '.join(q['sql'] for q in queries.captured_queries)
            in_sql = f'`users`.`id` IN ({self.user.pk}, {another_user.pk})'
            assert in_sql in queries_str
            assert len(queries.captured_queries) == 6
        assert response.status_code == 200
        doc = pq(response.content)
        assert str(self.user.pk) in doc('#result_list').text()
        assert str(another_user.pk) in doc('#result_list').text()

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
        assert b'Cannot delete user' not in response.content
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

    def test_can_delete_with_related_objects_with_admin_advanced_permission(
            self):
        # Add related instances...
        addon = addon_factory()
        addon_with_other_authors = addon_factory()
        AddonUser.objects.create(
            addon=addon_with_other_authors, user=user_factory())
        relations_that_should_be_deleted = [
            AddonUser.objects.create(
                addon=addon_with_other_authors, user=self.user),
            Rating.objects.create(
                addon=addon_factory(), rating=5, user=self.user),
            addon,  # Has no other author, should be deleted.
            collection_factory(author=self.user)
        ]
        relations_that_should_survive = [
            AbuseReport.objects.create(reporter=self.user),
            AbuseReport.objects.create(user=self.user),
            ActivityLog.create(user=self.user, action=amo.LOG.USER_EDITED),
            ReviewerScore.objects.create(user=self.user, score=42),
            addon_with_other_authors,  # Has other authors, should be kept.

            # Bit of a weird case, but because the user was the only author of
            # this add-on, the addonuser relation is kept, and both the add-on
            # and the user are soft-deleted. This is in contrast with the case
            # where the user is *not* the only author, in which case the
            # addonuser relation is deleted, but the add-on is left intact.
            AddonUser.objects.create(addon=addon, user=self.user),
        ]

        # Now test as normal.
        user = user_factory()
        assert not self.user.deleted
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        core.set_user(user)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 200
        assert b'Cannot delete user' not in response.content
        response = self.client.post(self.delete_url, {'post': 'yes'},
                                    follow=True)
        assert response.status_code == 200
        self.user.reload()
        assert self.user.deleted
        assert self.user.email is None
        alog = ActivityLog.objects.filter(
            action=amo.LOG.ADMIN_USER_ANONYMIZED.id).get()
        assert alog.arguments == [self.user]

        # Test the related instances we created earlier.
        for obj in relations_that_should_be_deleted:
            assert not obj.__class__.objects.filter(pk=obj.pk).exists()

        for obj in relations_that_should_survive:
            assert obj.__class__.objects.filter(pk=obj.pk).exists()

    def test_get_actions(self):
        user_admin = UserAdmin(UserProfile, admin.site)
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        assert list(user_admin.get_actions(request).keys()) == []

        request.user = user_factory()
        self.grant_permission(request.user, 'Users:Edit')
        assert list(user_admin.get_actions(request).keys()) == [
            'ban_action', 'reset_api_key_action', 'reset_session_action'
        ]

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

    def test_reset_api_key_action(self):
        another_user = user_factory()
        a_third_user = user_factory()

        APIKey.objects.create(user=self.user, is_active=True, key='foo')
        APIKeyConfirmation.objects.create(user=self.user)

        APIKeyConfirmation.objects.create(user=another_user)

        APIKey.objects.create(user=a_third_user, is_active=True, key='bar')
        APIKeyConfirmation.objects.create(user=a_third_user)

        users = UserProfile.objects.filter(
            pk__in=(another_user.pk, self.user.pk))
        user_admin = UserAdmin(UserProfile, admin.site)
        request = RequestFactory().get('/')
        request.user = user_factory()
        core.set_user(request.user)
        request._messages = default_messages_storage(request)
        user_admin.reset_api_key_action(request, users)
        # APIKeys should have been deactivated, APIKeyConfirmation deleted.
        assert self.user.api_keys.exists()
        assert not self.user.api_keys.filter(is_active=True).exists()
        assert not APIKeyConfirmation.objects.filter(user=self.user).exists()

        # This user didn't have api keys before, it shouldn't matter.
        assert not another_user.api_keys.exists()
        assert not another_user.api_keys.filter(is_active=True).exists()
        assert not APIKeyConfirmation.objects.filter(
            user=another_user).exists()

        # The 3rd user should be unaffected.
        assert a_third_user.api_keys.exists()
        assert a_third_user.api_keys.filter(is_active=True).exists()
        assert APIKeyConfirmation.objects.filter(user=a_third_user).exists()

        # We should see 2 activity logs.
        assert ActivityLog.objects.filter(
            action=amo.LOG.ADMIN_API_KEY_RESET.id).count() == 2

    def test_reset_session_action(self):
        assert self.user.auth_id
        another_user = user_factory()
        assert another_user.auth_id
        a_third_user = user_factory()
        assert a_third_user.auth_id
        old_auth_id = a_third_user.auth_id

        users = UserProfile.objects.filter(
            pk__in=(another_user.pk, self.user.pk))
        user_admin = UserAdmin(UserProfile, admin.site)
        request = RequestFactory().get('/')
        request.user = user_factory()
        core.set_user(request.user)
        request._messages = default_messages_storage(request)
        user_admin.reset_session_action(request, users)

        self.user.reload()
        assert self.user.auth_id is None
        another_user.reload()
        assert another_user.auth_id is None
        a_third_user.reload()
        assert a_third_user.auth_id == old_auth_id

    def test_reset_api_key_button_in_change_view(self):
        reset_api_key_url = reverse(
            'admin:users_userprofile_reset_api_key', args=(self.user.pk, ))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Users:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert reset_api_key_url in response.content.decode('utf-8')

    def test_session_button_in_change_view(self):
        reset_session_url = reverse(
            'admin:users_userprofile_reset_session', args=(self.user.pk, ))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Users:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert reset_session_url in response.content.decode('utf-8')

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
        assert response.redirect_chain[-1][0].endswith(self.detail_url)
        assert response.redirect_chain[-1][1] == 302
        self.user.reload()
        assert self.user.deleted
        assert self.user.email
        alog = ActivityLog.objects.latest('pk')
        assert alog.action == amo.LOG.ADMIN_USER_BANNED.id
        assert alog.arguments == [self.user]

    def test_reset_api_key(self):
        APIKey.objects.create(user=self.user, is_active=True, key='foo')
        APIKeyConfirmation.objects.create(user=self.user)

        reset_api_key_url = reverse(
            'admin:users_userprofile_reset_api_key', args=(self.user.pk, ))
        wrong_reset_api_key_url = reverse(
            'admin:users_userprofile_reset_api_key', args=(self.user.pk + 9, ))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        core.set_user(user)
        response = self.client.post(reset_api_key_url, follow=True)
        assert response.status_code == 403
        self.grant_permission(user, 'Users:Edit')
        response = self.client.get(reset_api_key_url, follow=True)
        assert response.status_code == 405  # Wrong http method.
        response = self.client.post(wrong_reset_api_key_url, follow=True)
        assert response.status_code == 404  # Wrong pk.

        assert self.user.api_keys.filter(is_active=True).exists()
        assert APIKeyConfirmation.objects.filter(user=self.user).exists()

        response = self.client.post(reset_api_key_url, follow=True)
        assert response.status_code == 200
        assert response.redirect_chain[-1][0].endswith(self.detail_url)
        assert response.redirect_chain[-1][1] == 302

        alog = ActivityLog.objects.latest('pk')
        assert alog.action == amo.LOG.ADMIN_API_KEY_RESET.id
        assert alog.arguments == [self.user]

        # APIKeys should have been deactivated, APIKeyConfirmation deleted.
        assert self.user.api_keys.exists()
        assert not self.user.api_keys.filter(is_active=True).exists()
        assert not APIKeyConfirmation.objects.filter(user=self.user).exists()

    def test_reset_session(self):
        assert self.user.auth_id
        reset_session_url = reverse(
            'admin:users_userprofile_reset_session', args=(self.user.pk, ))
        wrong_reset_session_url = reverse(
            'admin:users_userprofile_reset_session', args=(self.user.pk + 9, ))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.post(reset_session_url, follow=True)
        assert response.status_code == 403
        self.grant_permission(user, 'Users:Edit')
        response = self.client.get(reset_session_url, follow=True)
        assert response.status_code == 405  # Wrong http method.
        response = self.client.post(wrong_reset_session_url, follow=True)
        assert response.status_code == 404  # Wrong pk.

        response = self.client.post(reset_session_url, follow=True)
        assert response.status_code == 200
        assert response.redirect_chain[-1][0].endswith(self.detail_url)
        assert response.redirect_chain[-1][1] == 302

        alog = ActivityLog.objects.latest('pk')
        assert alog.action == amo.LOG.ADMIN_USER_SESSION_RESET.id
        assert alog.arguments == [self.user]

        self.user.reload()
        assert not self.user.auth_id

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
        assert response.redirect_chain[-1][0].endswith(self.detail_url)
        assert response.redirect_chain[-1][1] == 302

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
        assert str(model_admin.last_known_activity_time(self.user)) == ''

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

        assert (
            str(model_admin.last_known_activity_time(self.user)) ==
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
        addon_factory(users=[self.user], status=amo.STATUS_NOMINATED)
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

    def test_access_using_email(self):
        lookup_user = user_factory(email='foo@bar.xyz')
        detail_url_by_email = reverse(
            'admin:users_userprofile_change', args=(lookup_user.email,)
        )
        detail_url_final = reverse(
            'admin:users_userprofile_change', args=(lookup_user.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(detail_url_by_email, follow=False)
        self.assert3xx(response, detail_url_final, 301)


class TestEmailUserRestrictionAdmin(TestCase):
    def setUp(self):
        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:Tools')
        self.grant_permission(self.user, 'Admin:Advanced')

        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:users_emailuserrestriction_changelist')

    def test_list(self):
        EmailUserRestriction.objects.create(email_pattern='*@*foo.com')
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200


class TestIPNetworkUserRestrictionAdmin(TestCase):
    def setUp(self):
        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:Tools')
        self.grant_permission(self.user, 'Admin:Advanced')

        self.client.login(email=self.user.email)
        self.list_url = reverse(
            'admin:users_ipnetworkuserrestriction_changelist')

    def test_list(self):
        IPNetworkUserRestriction.objects.create(network='192.168.0.0/24')
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
