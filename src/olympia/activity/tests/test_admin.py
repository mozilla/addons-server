from django.urls import reverse

from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import TestCase, user_factory
from olympia.activity.models import ActivityLog, ReviewActionReasonLog
from olympia.reviewers.models import ReviewActionReason


class TestReviewActionReasonLogAdmin(TestCase):
    def setUp(self):
        self.admin_home_url = reverse('admin:index')
        self.list_url = reverse('admin:activity_reviewactionreasonlog_changelist')
        self.reason_1 = ReviewActionReason.objects.create(
            name='reason 1',
            is_active=True,
        )
        self.reason_2 = ReviewActionReason.objects.create(
            name='reason 2',
            is_active=True,
        )
        self.inactive_reason = ReviewActionReason.objects.create(
            name='b inactive reason',
            is_active=False,
        )

    def test_can_see_module_in_admin_with_super_access(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.model-reviewactionreasonlog')

    def test_can_not_see_module_in_admin_without_permissions(self):
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.model-reviewactionreasonlog')

    def test_select_includes_only_active_reasons(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        activity_log = ActivityLog.objects.create(action=amo.LOG.APPROVE_VERSION.id)
        reason_log = ReviewActionReasonLog.objects.create(
            activity_log=activity_log,
            reason=self.reason_1,
        )

        detail_url = reverse(
            'admin:activity_reviewactionreasonlog_change', args=(reason_log.pk,)
        )
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        # Only the two active reasons should be available.
        reason_options = doc('#id_reason option')
        assert len(reason_options) == 2
        assert reason_options.eq(0).text() == self.reason_1.name
        assert reason_options.eq(1).text() == self.reason_1.name

    def test_select_includes_inactive_reason_if_current_reason(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        activity_log = ActivityLog.objects.create(action=amo.LOG.APPROVE_VERSION.id)
        reason_log = ReviewActionReasonLog.objects.create(
            activity_log=activity_log,
            reason=self.inactive_reason,
        )

        detail_url = reverse(
            'admin:activity_reviewactionreasonlog_change', args=(reason_log.pk,)
        )
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        # All three reasons should be available, as the inactive one is current.
        reason_options = doc('#id_reason option')
        assert len(reason_options) == 3
