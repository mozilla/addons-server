import uuid

from django.conf import settings
from django.contrib import admin
from django.contrib.messages.storage import default_storage as default_messages_storage
from django.test import RequestFactory
from django.urls import reverse

from pyquery import PyQuery as pq

from olympia import core
from olympia.abuse.models import CinderPolicy
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    grant_permission,
    user_factory,
    version_factory,
)
from olympia.reviewers.admin import NeedsHumanReviewAdmin
from olympia.reviewers.models import NeedsHumanReview, ReviewActionReason, UsageTier


class TestNeedsHumanReviewAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:reviewers_needshumanreview_changelist')
        user_factory(pk=settings.TASK_USER_ID)

    def test_deactivate_action_end_to_end(self):
        addon = addon_factory()
        v1 = version_factory(addon=addon)
        v2 = version_factory(addon=addon)
        nhr0 = NeedsHumanReview.objects.create(
            version=v1, reason=NeedsHumanReview.REASONS.UNKNOWN
        )
        nhr1 = NeedsHumanReview.objects.create(
            version=v1, reason=NeedsHumanReview.REASONS.MANUALLY_SET_BY_REVIEWER
        )
        nhr2 = NeedsHumanReview.objects.create(
            version=v2, reason=NeedsHumanReview.REASONS.MANUALLY_SET_BY_REVIEWER
        )
        assert v1.due_date
        assert v2.due_date

        user = user_factory(email='admin@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        response = self.client.get(self.list_url)
        doc = pq(response.content)
        assert [
            option.attrib['value']
            for option in doc('.actions select[name=action] option')
        ] == ['', 'deactivate_selected', 'activate_selected']

        post_data = {
            'action': 'deactivate_selected',
            'select_across': '0',
            'index': '0',
            '_selected_action': [str(nhr1.pk), str(nhr2.pk)],
        }
        response = self.client.post(self.list_url, post_data)
        assert response.status_code == 302

        nhr0.reload()
        assert nhr0.is_active  # not part of the selected, so it's untouched.

        nhr1.reload()
        v1.reload()
        assert not nhr1.is_active
        assert v1.due_date  # Because it has another NeedsHumanReview

        nhr2.reload()
        v2.reload()
        assert not nhr2.is_active
        assert not v2.due_date  # No longer has any reason to have a due date.

    def test_deactivate_selected_action(self):
        request = RequestFactory().get('/')
        request.user = user_factory(email='admin@mozilla.com')
        self.grant_permission(request.user, '*:*')
        core.set_user(request.user)
        request._messages = default_messages_storage(request)

        addon = addon_factory()
        v1 = version_factory(addon=addon)
        v2 = version_factory(addon=addon)
        nhr0 = NeedsHumanReview.objects.create(
            version=v1, reason=NeedsHumanReview.REASONS.UNKNOWN
        )
        nhr1 = NeedsHumanReview.objects.create(
            version=v1, reason=NeedsHumanReview.REASONS.MANUALLY_SET_BY_REVIEWER
        )
        nhr2 = NeedsHumanReview.objects.create(
            version=v2, reason=NeedsHumanReview.REASONS.MANUALLY_SET_BY_REVIEWER
        )
        assert v1.due_date
        assert v2.due_date

        qs = NeedsHumanReview.objects.filter(pk__in=(nhr1.pk, nhr2.pk))
        nhr_admin = NeedsHumanReviewAdmin(NeedsHumanReview, admin.site)

        nhr_admin.deactivate_selected(request, qs)

        nhr0.reload()
        assert nhr0.is_active  # not part of the queryset, so it's untouched.

        nhr1.reload()
        v1.reload()
        assert not nhr1.is_active
        assert v1.due_date  # Because it has another NeedsHumanReview

        nhr2.reload()
        v2.reload()
        assert not nhr2.is_active
        assert not v2.due_date  # No longer has any reason to have a due date.

    def test_activate_selected_action(self):
        request = RequestFactory().get('/')
        request.user = user_factory(email='admin@mozilla.com')
        self.grant_permission(request.user, '*:*')
        core.set_user(request.user)
        request._messages = default_messages_storage(request)

        addon = addon_factory()
        v1 = version_factory(addon=addon)
        v2 = version_factory(addon=addon)
        nhr0 = NeedsHumanReview.objects.create(
            version=v1, reason=NeedsHumanReview.REASONS.UNKNOWN, is_active=False
        )
        nhr1 = NeedsHumanReview.objects.create(
            version=v1,
            reason=NeedsHumanReview.REASONS.MANUALLY_SET_BY_REVIEWER,
            is_active=False,
        )
        nhr2 = NeedsHumanReview.objects.create(
            version=v2,
            reason=NeedsHumanReview.REASONS.MANUALLY_SET_BY_REVIEWER,
            is_active=False,
        )
        assert not v1.due_date
        assert not v2.due_date

        qs = NeedsHumanReview.objects.filter(pk__in=(nhr1.pk, nhr2.pk))
        nhr_admin = NeedsHumanReviewAdmin(NeedsHumanReview, admin.site)

        nhr_admin.activate_selected(request, qs)

        nhr0.reload()
        assert not nhr0.is_active  # not part of the queryset, so it's untouched.

        nhr1.reload()
        v1.reload()
        assert nhr1.is_active
        assert v1.due_date

        nhr2.reload()
        v2.reload()
        assert nhr2.is_active
        assert v2.due_date


class TestReviewActionReasonAdmin(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory(email='someone@mozilla.com')
        grant_permission(cls.user, '*:*', 'Admins')

    def setUp(self):
        self.client.force_login(self.user)
        self.list_url = reverse('admin:reviewers_reviewactionreason_changelist')

    def test_list_no_permission(self):
        user = user_factory(email='nobody@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_list(self):
        foo = CinderPolicy.objects.create(name='Foo')
        CinderPolicy.objects.create(name='Bar', parent=foo, uuid=uuid.uuid4())
        zab = CinderPolicy.objects.create(name='Zab', parent=foo, uuid=uuid.uuid4())
        lorem = CinderPolicy.objects.create(name='Lorem', uuid=uuid.uuid4())
        CinderPolicy.objects.create(name='Ipsum', uuid=uuid.uuid4())
        ReviewActionReason.objects.create(
            name='Attached to Zab', cinder_policy=zab, canned_response='.'
        )
        ReviewActionReason.objects.create(
            name='Attached to Lorem', cinder_policy=lorem, canned_response='.'
        )
        ReviewActionReason.objects.create(
            name='Also attached to Lorem', cinder_policy=lorem, canned_response='.'
        )

        with self.assertNumQueries(6):
            # - 2 savepoints (tests)
            # - 2 current user & groups
            # - 1 count review action reasons
            # - 1 review action reasons (+ cinder policies and parents in one query)
            response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#result_list tbody tr')) == ReviewActionReason.objects.count()
        assert (
            doc('#result_list th.field-name').text()
            == 'Also attached to Lorem Attached to Lorem Attached to Zab'
        )
        assert (
            doc('#result_list td.field-linked_cinder_policy')[2].text_content()
            == 'Foo, specifically Zab'
        )


class TestUsageTierAdmin(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory(email='someone@mozilla.com')
        grant_permission(cls.user, '*:*', 'Admins')

    def setUp(self):
        self.client.force_login(self.user)
        self.list_url = reverse('admin:reviewers_usagetier_changelist')
        self.tier0 = UsageTier.objects.create()
        self.tier1 = UsageTier.objects.create(upper_adu_threshold=10)
        self.tier2 = UsageTier.objects.create(
            lower_adu_threshold=10, upper_adu_threshold=20
        )
        self.tier3 = UsageTier.objects.create(lower_adu_threshold=20)

    def test_list(self):
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#result_list tbody tr')) == UsageTier.objects.count()

    def test_change_pages_load(self):
        for tier in UsageTier.objects.all():
            url = tier.get_admin_url_path()
            response = self.client.get(url)
            assert response.status_code == 200
