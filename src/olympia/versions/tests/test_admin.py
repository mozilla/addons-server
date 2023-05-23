from datetime import datetime

from django.conf import settings
from django.urls import reverse

from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.reviewers.models import NeedsHumanReview
from olympia.versions.models import InstallOrigin


class TestVersionAdmin(TestCase):
    def test_authorized_user_has_access(self):
        addon = addon_factory()
        version = addon.current_version
        detail_url = reverse('admin:versions_version_change', args=(version.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.force_login(user)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200

        doc = pq(response.content)
        assert doc('textarea#id_release_notes_0').length == 1

    def test_unauthorized_user_has_no_access(self):
        addon = addon_factory()
        version = addon.current_version
        detail_url = reverse('admin:versions_version_change', args=(version.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 403

    def test_change_due_date(self):
        addon = addon_factory()
        version = addon.current_version
        detail_url = reverse('admin:versions_version_change', args=(version.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.force_login(user)
        post_data = {
            # Django wants the whole form to be submitted, unfortunately.
            'addon': addon.pk,
            'release_notes_en-us': '',
            'approval_notes': '',
            'license': version.license.pk,
            'source': {},
            'due_date_0': '2023-02-21',
            'due_date_1': '12:30:00',
            'reviewerflags-TOTAL_FORMS': '1',
            'reviewerflags-INITIAL_FORMS': '0',
            'reviewerflags-MIN_NUM_FORMS': '0',
            'reviewerflags-MAX_NUM_FORMS': '1',
            'reviewerflags-0-pending_rejection_0': '',
            'reviewerflags-0-pending_rejection_1': '',
            'reviewerflags-0-version': version.pk,
            'needshumanreview_set-TOTAL_FORMS': '0',
            'needshumanreview_set-INITIAL_FORMS': '0',
            'needshumanreview_set-MIN_NUM_FORMS': '0',
            'needshumanreview_set-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(detail_url, post_data, follow=True)
        assert response.status_code == 200
        version.reload()
        assert version.due_date == datetime(2023, 2, 21, 12, 30)

    def test_new_needshumanreviewinline_is_saved(self):
        # Using default Django form, saving a new NeedsHumanReview through the
        # inline with no changes to the default values would not work. We have
        # a custom form to work around that issue.
        addon = addon_factory()
        version = addon.current_version
        detail_url = reverse('admin:versions_version_change', args=(version.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.force_login(user)
        post_data = {
            'addon': addon.pk,
            'release_notes_en-us': '',
            'approval_notes': '',
            'license': version.license.pk,
            'source': {},
            'due_date_0': '2023-02-21',
            'due_date_1': '12:30:00',
            'reviewerflags-TOTAL_FORMS': '1',
            'reviewerflags-INITIAL_FORMS': '0',
            'reviewerflags-MIN_NUM_FORMS': '0',
            'reviewerflags-MAX_NUM_FORMS': '1',
            'reviewerflags-0-pending_rejection_0': '',
            'reviewerflags-0-pending_rejection_1': '',
            'reviewerflags-0-version': version.pk,
            'needshumanreview_set-TOTAL_FORMS': '1',
            'needshumanreview_set-INITIAL_FORMS': '0',
            'needshumanreview_set-MIN_NUM_FORMS': '0',
            'needshumanreview_set-MAX_NUM_FORMS': '1000',
            'needshumanreview_set-0-id': '',
            'needshumanreview_set-0-version': version.pk,
            'needshumanreview_set-0-is_active': 'on',
        }
        response = self.client.post(detail_url, post_data, follow=True)
        assert response.status_code == 200
        version.reload()
        assert version.needshumanreview_set.count() == 1
        needs_human_review = version.needshumanreview_set.get()
        assert needs_human_review.reason == NeedsHumanReview.REASON_UNKNOWN
        assert needs_human_review.is_active

    def test_existing_needshumanreviewinline_is_not_saved_if_no_changes(self):
        user_factory(pk=settings.TASK_USER_ID)
        addon = addon_factory()
        version = addon.current_version
        needs_human_review = NeedsHumanReview.objects.create(version=version)
        old_modified = self.days_ago(42)
        needs_human_review.update(modified=old_modified)
        version.update(modified=old_modified)
        detail_url = reverse('admin:versions_version_change', args=(version.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.force_login(user)
        post_data = {
            'addon': addon.pk,
            'release_notes_en-us': '',
            'approval_notes': '',
            'license': version.license.pk,
            'source': {},
            'due_date_0': '',
            'due_date_1': '',
            'reviewerflags-TOTAL_FORMS': '1',
            'reviewerflags-INITIAL_FORMS': '0',
            'reviewerflags-MIN_NUM_FORMS': '0',
            'reviewerflags-MAX_NUM_FORMS': '1',
            'reviewerflags-0-pending_rejection_0': '',
            'reviewerflags-0-pending_rejection_1': '',
            'reviewerflags-0-version': version.pk,
            'needshumanreview_set-TOTAL_FORMS': '1',
            'needshumanreview_set-INITIAL_FORMS': '1',
            'needshumanreview_set-MIN_NUM_FORMS': '0',
            'needshumanreview_set-MAX_NUM_FORMS': '1000',
            'needshumanreview_set-0-id': needs_human_review.pk,
            'needshumanreview_set-0-version': version.pk,
            'needshumanreview_set-0-is_active': 'on',
        }
        response = self.client.post(detail_url, post_data, follow=True)
        assert response.status_code == 200
        assert version.reload().modified != old_modified
        assert needs_human_review.reload().modified == old_modified
        assert needs_human_review.is_active

    def test_existing_needshumanreviewinline_is_saved_if_changes(self):
        user_factory(pk=settings.TASK_USER_ID)
        addon = addon_factory()
        version = addon.current_version
        needs_human_review = NeedsHumanReview.objects.create(version=version)
        old_modified = self.days_ago(42)
        needs_human_review.update(modified=old_modified)
        version.update(modified=old_modified)
        detail_url = reverse('admin:versions_version_change', args=(version.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.force_login(user)
        post_data = {
            'addon': addon.pk,
            'release_notes_en-us': '',
            'approval_notes': '',
            'license': version.license.pk,
            'source': {},
            'due_date_0': '',
            'due_date_1': '',
            'reviewerflags-TOTAL_FORMS': '1',
            'reviewerflags-INITIAL_FORMS': '0',
            'reviewerflags-MIN_NUM_FORMS': '0',
            'reviewerflags-MAX_NUM_FORMS': '1',
            'reviewerflags-0-pending_rejection_0': '',
            'reviewerflags-0-pending_rejection_1': '',
            'reviewerflags-0-version': version.pk,
            'needshumanreview_set-TOTAL_FORMS': '1',
            'needshumanreview_set-INITIAL_FORMS': '1',
            'needshumanreview_set-MIN_NUM_FORMS': '0',
            'needshumanreview_set-MAX_NUM_FORMS': '1000',
            'needshumanreview_set-0-id': needs_human_review.pk,
            'needshumanreview_set-0-version': version.pk,
            'needshumanreview_set-0-is_active': '',
        }
        response = self.client.post(detail_url, post_data, follow=True)
        assert response.status_code == 200
        assert version.reload().modified != old_modified
        assert needs_human_review.reload().modified != old_modified
        assert not needs_human_review.is_active


class TestInstallOriginAdmin(TestCase):
    def test_list(self):
        install_origin1 = InstallOrigin.objects.create(
            version=addon_factory().current_version,
            origin='https://one.example.com',
            base_domain='one.example.com',
        )
        install_origin2 = InstallOrigin.objects.create(
            version=addon_factory().current_version,
            origin='https://two.example.com',
            base_domain='two.example.com',
        )
        install_origin3 = InstallOrigin.objects.create(
            version=addon_factory().current_version,
            origin='https://three.example.com',
            base_domain='three.example.com',
        )
        list_url = reverse('admin:versions_installorigin_changelist')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        with self.assertNumQueries(6):
            # - 2 SAVEPOINTs
            # - 2 user & groups
            # - 1 count
            #     (show_full_result_count=False so we avoid the duplicate)
            # - 1 install origins
            response = self.client.get(list_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#result_list tbody tr')) == 3
        assert doc('#result_list tbody tr:eq(2)').text() == '\n'.join(
            [
                str(install_origin1.id),
                install_origin1.version.addon.guid,
                install_origin1.version.version,
                install_origin1.origin,
                install_origin1.base_domain,
            ]
        )
        assert doc('#result_list tbody tr:eq(1)').text() == '\n'.join(
            [
                str(install_origin2.id),
                install_origin2.version.addon.guid,
                install_origin2.version.version,
                install_origin2.origin,
                install_origin2.base_domain,
            ]
        )
        assert doc('#result_list tbody tr:eq(0)').text() == '\n'.join(
            [
                str(install_origin3.id),
                install_origin3.version.addon.guid,
                install_origin3.version.version,
                install_origin3.origin,
                install_origin3.base_domain,
            ]
        )

    def test_add_disabled(self):
        add_url = reverse('admin:versions_installorigin_add')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        response = self.client.get(add_url, follow=True)
        assert response.status_code == 403

    def test_delete_disabled(self):
        install_origin = InstallOrigin.objects.create(
            version=addon_factory().current_version,
            origin='https://example.com',
            base_domain='example.com',
        )
        delete_url = reverse(
            'admin:versions_installorigin_delete', args=(install_origin.pk,)
        )
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 403

    def test_only_readonly_fields(self):
        install_origin = InstallOrigin.objects.create(
            version=addon_factory().current_version,
            origin='https://example.com',
            base_domain='example.com',
        )
        detail_url = reverse(
            'admin:versions_installorigin_change', args=(install_origin.pk,)
        )
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#installorigin_form')
        assert not doc('#installorigin_form input:not([type=hidden])')
