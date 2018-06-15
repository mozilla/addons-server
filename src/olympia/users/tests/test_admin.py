from django.conf import settings
from django.utils.dateformat import DateFormat

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

from pyquery import PyQuery as pq


class TestUserAdmin(TestCase):
    def setUp(self):
        self.user = user_factory()
        self.list_url = reverse('admin:users_userprofile_changelist')
        self.detail_url = reverse(
            'admin:users_userprofile_change', args=(self.user.pk,)
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
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Users:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        response = self.client.post(
            self.detail_url, {'username': 'foo', 'email': self.user.email},
            follow=True)
        assert response.status_code == 200
        assert self.user.reload().username == 'foo'

    def test_picture_img(self):
        model_admin = UserAdmin(UserProfile, None)
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
        model_admin = UserAdmin(UserProfile, None)
        doc = pq(model_admin.known_ip_adresses(self.user))
        result = doc('ul li').text().split()
        assert len(result) == 4
        assert (set(result) ==
                set(['130.1.2.4', '128.1.2.3', '129.1.2.4', '127.1.2.3']))

    def test_last_known_activity_time(self):
        someone_else = user_factory(username='someone_else')
        addon = addon_factory()

        model_admin = UserAdmin(UserProfile, None)
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
        model_admin = UserAdmin(UserProfile, None)
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
