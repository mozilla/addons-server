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

    def test_select_labels_inactive_reasons(self):
        reason_1 = ReviewActionReason.objects.create(
            name='reason 1',
            is_active=True,
        )
        inactive_reason = ReviewActionReason.objects.create(
            name='inactive reason',
            is_active=False,
        )
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        activity_log = ActivityLog.objects.create(action=amo.LOG.APPROVE_VERSION.id)
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
        assert reason_options.eq(0).text() == inactive_reason.name + ' (** inactive **)'
        assert reason_options.eq(1).text() == reason_1.name
