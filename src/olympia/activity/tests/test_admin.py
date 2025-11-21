from django.urls import reverse

from pyquery import PyQuery as pq

from olympia import activity, amo, core
from olympia.activity.models import ActivityLog, ReviewActionReasonLog
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.reviewers.models import ReviewActionReason


class TestActivityLogAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:activity_activitylog_changelist')

    def test_list(self):
        author = user_factory()
        addon1 = addon_factory()
        activity.log_create(
            amo.LOG.ADD_VERSION, addon1.current_version, addon1, user=author
        )
        addon2 = addon_factory()
        activity.log_create(
            amo.LOG.ADD_VERSION, addon2.current_version, addon2, user=author
        )
        addon3 = addon_factory()
        activity.log_create(
            amo.LOG.ADD_VERSION, addon3.current_version, addon3, user=author
        )

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)

        with self.assertNumQueries(11):
            # - 2 savepoints/release
            # - 2 user and groups
            # - 1 count for pagination
            # - 1 activities
            # - 1 all users from activities
            # - 1 all versions from activities
            # - 1 all translations from those versions
            # - 1 all add-ons from activities
            # - 1 all translations for those add-ons
            response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#result_list tbody tr')) == 4  # 3 add versions, 1 log in.

    def test_search_for_single_ip(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        user2 = user_factory()
        user3 = user_factory()
        addon = addon_factory(users=[user3])
        with core.override_remote_addr_or_metadata(ip_address='127.0.0.2'):
            user2.update(email='foo@bar.com')
            # That will make user2 match our query.
            ActivityLog.objects.create(amo.LOG.LOG_IN, user=user2)
        with core.override_remote_addr_or_metadata(ip_address='127.0.0.2'):
            # That will make user3 match our query.
            ActivityLog.objects.create(
                amo.LOG.ADD_VERSION, addon.current_version, addon, user=user3
            )
        with core.override_remote_addr_or_metadata(ip_address='127.0.0.1'):
            extra_user = user_factory()  # Extra user that shouldn't match
            ActivityLog.objects.create(amo.LOG.LOG_IN, user=extra_user)
        with self.assertNumQueries(11):
            # - 2 savepoints/release
            # - 2 user and groups
            # - 1 count for pagination
            # - 1 activities
            # - 1 all users from activities
            # - 1 all versions from activities
            # - 1 all translations from those versions
            # - 1 all add-ons from activities
            # - 1 all translations for those add-ons
            response = self.client.get(self.list_url, {'q': '127.0.0.2'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert len(doc('#result_list tbody tr')) == 2
        # Make sure it's the right records.
        assert set(
            (
                doc('.field-user_link')[0].text_content(),
                doc('.field-user_link')[1].text_content(),
            )
        ) == {str(user2), str(user3)}
        # Make sure login ip is now displayed, and has the right value.
        # (twice since 2 rows are matching)
        assert doc('.field-known_ip_adresses').text() == '127.0.0.2 127.0.0.2'

    def test_search_for_ja4(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        user2 = user_factory()
        user3 = user_factory()
        with core.override_remote_addr_or_metadata(
            ip_address='127.0.0.2', metadata={'Client-JA4': 'some_ja4'}
        ):
            user2.update(email='foo@bar.com')
            # Will match (ja4 we'll be searching for)
            ActivityLog.objects.create(amo.LOG.LOG_IN, user=user2)
        with core.override_remote_addr_or_metadata(
            ip_address='127.0.0.3', metadata={'Client-JA4': 'some_other_ja4'}
        ):
            # Won't match (different ja4)
            ActivityLog.objects.create(amo.LOG.LOG_IN, user=user3)
        with core.override_remote_addr_or_metadata(ip_address='127.0.0.1'):
            extra_user = user_factory()
            # Won't match (no ja4)
            ActivityLog.objects.create(amo.LOG.LOG_IN, user=extra_user)
        with self.assertNumQueries(7):
            # - 2 savepoints/release
            # - 2 user and groups
            # - 1 count for pagination
            # - 1 activities
            # - 1 all users from activities
            response = self.client.get(self.list_url, {'q': 'some_ja4'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert len(doc('#result_list tbody tr')) == 1
        # Make sure it's the right records.
        assert doc('.field-user_link')[0].text_content() == str(user2)
        assert doc('.field-ja4').text() == 'some_ja4'

    def test_escaping_and_links(self):
        user = user_factory(
            email='someone@mozilla.com', display_name='<script>alert(52)</script>'
        )
        addon = addon_factory(name='<script>alert(41)</script>')
        activity.log_create(
            amo.LOG.ADD_VERSION, addon.current_version, addon, user=user
        )
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        content = response.content.decode('utf-8)')
        assert (
            '<a href="http://testserver/en-US/admin/models/users/userprofile/'
            f'{user.pk}/change/">&lt;script&gt;alert(52)&lt;/script&gt;</a> '
            'logged in.'
        ) in content
        assert (
            'Version <a href="http://testserver/en-US/admin/models/versions/version/'
            f'{addon.current_version.pk}/change/">{addon.current_version.version}</a>'
            f' added to <a href="http://testserver/en-US/admin/models/addons/addon/'
            f'{addon.pk}/change/">&lt;script&gt;alert(41)&lt;/script&gt;</a>'
        ) in content


class TestReviewActionReasonLogAdmin(TestCase):
    def setUp(self):
        self.admin_home_url = reverse('admin:index')
        self.list_url = reverse('admin:activity_reviewactionreasonlog_changelist')

    def test_can_see_module_in_admin_with_super_access(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.model-reviewactionreasonlog')

    def test_can_not_see_module_in_admin_without_permissions(self):
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.model-reviewactionreasonlog')

    def test_select_labels_inactive_reasons(self):
        reason_1 = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='.'
        )
        inactive_reason = ReviewActionReason.objects.create(
            name='inactive reason', is_active=False, canned_response='.'
        )
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        activity_log = ActivityLog.objects.create(
            action=amo.LOG.APPROVE_VERSION.id, user=user
        )
        reason_log = ReviewActionReasonLog.objects.create(
            activity_log=activity_log,
            reason=reason_1,
        )

        detail_url = reverse(
            'admin:activity_reviewactionreasonlog_change', args=(reason_log.pk,)
        )
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        reason_options = doc('#id_reason option')
        assert len(reason_options) == 2
        assert reason_options.eq(0).text() == '(** inactive **) ' + inactive_reason.name
        assert reason_options.eq(1).text() == reason_1.name
