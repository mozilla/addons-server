import os.path
import zipfile
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.files import temp
from django.core.files.base import File as DjangoFile
from django.urls import reverse

from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.activity.utils import ACTIVITY_MAIL_GROUP
from olympia.addons.models import Addon, AddonApprovalsCounter
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    TestCase,
    block_factory,
    create_default_webext_appversion,
    formset,
    initial,
    reverse_ns,
    user_factory,
    version_factory,
)
from olympia.applications.models import AppVersion
from olympia.blocklist.models import BlockType
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.files.models import File
from olympia.reviewers.models import AutoApprovalSummary
from olympia.users.models import Group, UserProfile
from olympia.versions.models import ApplicationsVersions, Version, VersionReviewerFlags


class TestVersion(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.client.force_login(UserProfile.objects.get(email='del@icio.us'))
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.addon = self.get_addon()
        self.version = Version.objects.get(id=81551)
        self.url = self.addon.get_dev_url('versions')
        self.disable_url = self.addon.get_dev_url('disable')
        self.enable_url = self.addon.get_dev_url('enable')
        self.delete_url = reverse('devhub.versions.delete', args=['a3615'])
        self.delete_data = {'addon_id': self.addon.pk, 'version_id': self.version.pk}

    def get_addon(self):
        return Addon.objects.get(id=3615)

    def get_doc(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        return pq(response.content)

    def test_version_status_public(self):
        doc = self.get_doc()
        assert doc('.addon-status')

        self.addon.update(status=amo.STATUS_DISABLED, disabled_by_user=True)
        doc = self.get_doc()
        assert doc('.addon-status .status-admin-disabled')
        assert doc('.addon-status .status-admin-disabled').text() == (
            'Disabled by Mozilla'
        )

        self.addon.update(disabled_by_user=False)
        doc = self.get_doc()
        assert doc('.addon-status .status-admin-disabled').text() == (
            'Disabled by Mozilla'
        )

        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        doc = self.get_doc()
        assert doc('.addon-status .status-disabled').text() == ('Invisible')

    def test_blocked_version(self):
        task_user = UserProfile.objects.get(pk=settings.TASK_USER_ID)
        v3 = version_factory(addon=self.addon, version='3.0')
        v4 = version_factory(addon=self.addon, version='4.0.1')
        block_factory(version_ids=[v3.pk, v4.pk], updated_by=task_user)
        for version in (v3, v4):
            version.file.update(status=amo.STATUS_DISABLED)
        doc = self.get_doc()
        assert (
            doc('#version-list .file-status-text')[0].text_content().strip()
            == 'Blocked'
        )
        assert (
            doc('#version-list .file-status-text')[1].text_content().strip()
            == 'Blocked'
        )

        v4.blockversion.update(block_type=BlockType.SOFT_BLOCKED)
        doc = self.get_doc()
        assert (
            doc('#version-list .file-status-text')[0].text_content().strip()
            == 'Restricted'
        )
        assert (
            doc('#version-list .file-status-text')[1].text_content().strip()
            == 'Blocked'
        )

    def test_label_open_marked_safe(self):
        doc = self.get_doc()
        assert '<strong>Visible:</strong>' in doc.html()

        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        doc = self.get_doc()
        assert '<strong>Invisible:</strong>' in doc.html()

    def test_upload_link_label_in_edit_nav(self):
        url = reverse('devhub.versions.edit', args=(self.addon.slug, self.version.pk))
        response = self.client.get(url)
        link = pq(response.content)('.addon-status>.addon-upload>strong>a')
        assert link.text() == 'Upload New Version'
        assert link.attr('href') == (
            reverse('devhub.submit.version', args=[self.addon.slug])
        )

        # Still show for "Invisible" add-ons (they can submit unlisted versions)
        self.addon.update(disabled_by_user=True)
        response = self.client.get(url)
        link = pq(response.content)('.addon-status>.addon-upload>strong>a')
        assert link.text() == 'Upload New Version'
        assert link.attr('href') == (
            reverse('devhub.submit.version', args=[self.addon.slug])
        )

        # Don't show for STATUS_DISABLED addons.
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(url)
        assert not pq(response.content)('.addon-status>.addon-upload>strong>a')

    def test_delete_message(self):
        """Make sure we warn our users of the pain they will feel."""
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#modal-delete p').eq(0).text() == (
            'Deleting your add-on will permanently delete all versions and '
            'files you have submitted for this add-on, listed or not. '
            'All versions will be Restricted, which will disable and prevent any '
            'further installation in Firefox. '
            'Existing users can choose to re-enable the add-on. '
            'The add-on ID cannot be restored and will forever be unusable '
            'for submission.'
        )

    def test_delete_message_incomplete(self):
        """
        If an addon has status = 0, they shouldn't be bothered with a
        deny list threat if they hit delete.
        """
        # Need to hard delete the version or add-on will be soft-deleted.
        self.addon.current_version.delete(hard=True)
        self.addon.reload()
        assert self.addon.status == amo.STATUS_NULL
        response = self.client.get(self.url)
        doc = pq(response.content)
        # Normally 2 paragraphs, one is the warning which we should take out.
        assert doc('#modal-delete p.warning').length == 0

    def test_delete_version(self):
        self.client.post(self.delete_url, self.delete_data)
        assert not Version.objects.filter(pk=81551).exists()
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id).count() == 1

    def test_version_delete_version_deleted(self):
        self.version.delete()
        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 404

    def test_cant_delete_version(self):
        self.client.logout()
        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 302
        assert Version.objects.filter(pk=81551).exists()

    def test_version_delete_status_null(self):
        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 302
        assert self.addon.versions.count() == 0
        assert Addon.objects.get(id=3615).status == amo.STATUS_NULL

    def test_version_delete_with_rejected_listing(self):
        AddonApprovalsCounter.objects.create(
            addon=self.addon,
            content_review_status=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL,
        )
        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 302
        assert self.addon.versions.count() == 0
        assert Addon.objects.get(id=3615).status == amo.STATUS_REJECTED

    def test_disable_version(self):
        self.delete_data['disable_version'] = ''
        self.client.post(self.delete_url, self.delete_data)
        assert Version.objects.get(pk=81551).is_user_disabled
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id).count() == 0
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 1
        )

    def test_disable_version_with_rejected_listing(self):
        AddonApprovalsCounter.objects.create(
            addon=self.addon,
            content_review_status=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL,
        )
        self.test_disable_version()
        assert Addon.objects.get(id=3615).status == amo.STATUS_REJECTED

    def test_cant_disable_or_delete_current_version_recommended(self):
        # If the add-on is recommended you can't disable or delete the current
        # version.
        self.make_addon_promoted(
            self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )
        assert self.version == self.addon.current_version
        self.client.post(self.delete_url, self.delete_data)
        assert Version.objects.filter(pk=81551).exists()
        assert not Version.objects.get(pk=81551).is_user_disabled
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id).count() == 0
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 0
        )

        self.delete_data['disable_version'] = ''
        self.client.post(self.delete_url, self.delete_data)
        assert Version.objects.filter(pk=81551).exists()
        assert not Version.objects.get(pk=81551).is_user_disabled
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id).count() == 0
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 0
        )

    def test_can_disable_or_delete_current_ver_if_previous_recommended(self):
        # If the add-on is recommended you *can* disable or delete the current
        # version if the previous version is approved for recommendation too.
        self.make_addon_promoted(
            self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )
        previous_version = self.version
        self.version = version_factory(addon=self.addon, promotion_approved=True)
        self.addon.reload()
        assert self.version == self.addon.current_version
        assert previous_version != self.version

        self.delete_data['version_id'] = self.version.id
        self.delete_data['disable_version'] = ''
        self.client.post(self.delete_url, self.delete_data)
        assert Version.objects.filter(pk=self.version.id).exists()
        assert Version.objects.get(pk=self.version.id).is_user_disabled
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id).count() == 0
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 1
        )

        del self.delete_data['disable_version']
        self.client.post(self.delete_url, self.delete_data)
        assert not Version.objects.filter(pk=self.version.id).exists()
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id).count() == 1
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 1
        )

        self.addon.reload()
        assert self.addon.current_version == previous_version
        # It's still recommended.
        assert (
            PROMOTED_GROUP_CHOICES.RECOMMENDED in self.addon.promoted_groups().group_id
        )

    def test_can_still_disable_or_delete_old_version_recommended(self):
        # If the add-on is recommended, you can still disable or delete older
        # versions than the current one.
        self.make_addon_promoted(
            self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )
        version_factory(addon=self.addon, promotion_approved=True)
        self.addon.reload()
        assert self.version != self.addon.current_version

        self.delete_data['disable_version'] = ''
        self.client.post(self.delete_url, self.delete_data)
        assert Version.objects.filter(pk=81551).exists()
        assert Version.objects.get(pk=81551).is_user_disabled
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id).count() == 0
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 1
        )

        del self.delete_data['disable_version']
        self.client.post(self.delete_url, self.delete_data)
        assert not Version.objects.filter(pk=81551).exists()
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id).count() == 1
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 1
        )

    def test_can_still_disable_or_delete_current_version_unapproved(self):
        # If the add-on is in recommended group but hasn't got approval yet,
        # then deleting the current version is fine.
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        assert self.version == self.addon.current_version

        self.delete_data['disable_version'] = ''
        self.client.post(self.delete_url, self.delete_data)
        assert Version.objects.filter(pk=81551).exists()
        assert Version.objects.get(pk=81551).is_user_disabled
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id).count() == 0
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 1
        )

        del self.delete_data['disable_version']
        self.client.post(self.delete_url, self.delete_data)
        assert not Version.objects.filter(pk=81551).exists()
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id).count() == 1
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 1
        )

    def test_reenable_version(self):
        Version.objects.get(pk=81551).file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            status_disabled_reason=File.STATUS_DISABLED_REASONS.DEVELOPER,
        )
        self.reenable_url = reverse('devhub.versions.reenable', args=['a3615'])
        response = self.client.post(self.reenable_url, self.delete_data, follow=True)
        assert response.status_code == 200
        assert not Version.objects.get(pk=81551).is_user_disabled
        assert ActivityLog.objects.filter(action=amo.LOG.ENABLE_VERSION.id).count() == 1

    def test_reenable_deleted_version(self):
        Version.objects.get(pk=81551).delete()
        self.delete_url = reverse('devhub.versions.reenable', args=['a3615'])
        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 404
        assert ActivityLog.objects.filter(action=amo.LOG.ENABLE_VERSION.id).count() == 0

    def _extra_version_and_file(self, status):
        version = Version.objects.get(id=81551)

        version_two = version_factory(
            addon=self.addon,
            license=version.license,
            file_kw={'status': status},
        )
        return version_two, version_two.file

    def test_version_delete_status(self):
        self._extra_version_and_file(amo.STATUS_APPROVED)

        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 302
        assert self.addon.versions.count() == 1
        assert Addon.objects.get(id=3615).status == amo.STATUS_APPROVED

    def test_version_delete_status_unreviewed(self):
        self._extra_version_and_file(amo.STATUS_AWAITING_REVIEW)

        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 302
        assert self.addon.versions.count() == 1
        assert Addon.objects.get(id=3615).status == amo.STATUS_NOMINATED

    def test_user_can_disable_addon(self):
        version = self.addon.current_version
        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=False)
        response = self.client.post(self.disable_url)
        assert response.status_code == 302
        addon = Addon.objects.get(id=3615)
        version.reload()
        assert addon.disabled_by_user
        assert addon.status == amo.STATUS_APPROVED

        # Check we didn't change the status of the files.
        assert version.file.status == amo.STATUS_APPROVED

        entry = ActivityLog.objects.exclude(action=amo.LOG.LOG_IN.id).get()
        assert entry.action == amo.LOG.USER_DISABLE.id
        msg = entry.to_string()
        assert str(self.addon.name) in msg, 'Unexpected: %r' % msg

    def test_user_can_disable_addon_pending_version(self):
        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=False)
        (new_version, _) = self._extra_version_and_file(amo.STATUS_AWAITING_REVIEW)
        assert self.addon.find_latest_version(channel=amo.CHANNEL_LISTED) == new_version

        response = self.client.post(self.disable_url)
        assert response.status_code == 302
        addon = Addon.objects.get(id=3615)
        assert addon.disabled_by_user
        assert addon.status == amo.STATUS_APPROVED

        # Check we disabled the file pending review.
        new_version.file.reload()
        assert new_version.file.status == amo.STATUS_DISABLED
        # latest version should be reset when the file/version was disabled.
        assert self.addon.find_latest_version(channel=amo.CHANNEL_LISTED) != new_version

        entry = ActivityLog.objects.latest('pk')
        assert entry.action == amo.LOG.USER_DISABLE.id
        msg = entry.to_string()
        assert str(self.addon.name) in msg, 'Unexpected: %r' % msg

    def test_disabling_addon_awaiting_review_disables_version(self):
        self.addon.update(status=amo.STATUS_NOMINATED, disabled_by_user=False)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)

        res = self.client.post(self.disable_url)
        assert res.status_code == 302
        addon = Addon.objects.get(id=3615)
        assert addon.disabled_by_user
        assert addon.status == amo.STATUS_NULL

        # Check we disabled the file pending review.
        self.version = Version.objects.get(id=self.version.id)
        assert self.version.file.status == amo.STATUS_DISABLED

    def test_user_get(self):
        assert self.client.get(self.enable_url).status_code == 405

    def test_user_can_enable_addon(self):
        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        response = self.client.post(self.enable_url)
        self.assert3xx(response, self.url, 302)
        addon = self.get_addon()
        assert not addon.disabled_by_user
        assert addon.status == amo.STATUS_APPROVED

        entry = ActivityLog.objects.exclude(action=amo.LOG.LOG_IN.id).get()
        assert entry.action == amo.LOG.USER_ENABLE.id
        msg = entry.to_string()
        assert str(self.addon.name) in msg, 'Unexpected: %r' % msg

    def test_unprivileged_user_cant_disable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        response = self.client.post(self.disable_url)
        assert response.status_code == 302
        assert not Addon.objects.get(id=3615).disabled_by_user

    def test_non_owner_cant_disable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        response = self.client.post(self.disable_url)
        assert response.status_code == 403
        assert not Addon.objects.get(id=3615).disabled_by_user

    def test_non_owner_cant_enable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        response = self.client.get(self.enable_url)
        assert response.status_code == 403
        assert not Addon.objects.get(id=3615).disabled_by_user

    def test_non_owner_cant_change_status(self):
        """A non-owner can't use the radio buttons."""
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_published_addon_radio(self):
        """Published (listed) addon is selected: can hide or publish."""
        self.addon.update(disabled_by_user=False)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.enable-addon').attr('checked') == 'checked'
        enable_url = self.addon.get_dev_url('enable')
        assert doc('.enable-addon').attr('data-url') == enable_url
        assert not doc('.enable-addon').attr('disabled')
        assert doc('#modal-disable')
        assert not doc('.disable-addon').attr('checked')
        assert not doc('.disable-addon').attr('disabled')

    def test_hidden_addon_radio(self):
        """Hidden (disabled) addon is selected: can hide or publish."""
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('.enable-addon').attr('checked')
        assert not doc('.enable-addon').attr('disabled')
        assert doc('.disable-addon').attr('checked') == 'checked'
        assert not doc('.disable-addon').attr('disabled')
        assert not doc('#modal-disable')

    def test_status_disabled_addon_radio(self):
        """Disabled by Mozilla addon: hidden selected, can't change status."""
        self.addon.update(status=amo.STATUS_DISABLED, disabled_by_user=False)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('.enable-addon').attr('checked')
        assert doc('.enable-addon').attr('disabled') == 'disabled'
        assert doc('.disable-addon').attr('checked') == 'checked'
        assert doc('.disable-addon').attr('disabled') == 'disabled'

    def test_no_listed_versions_already_enabled(self):
        self.addon.versions.all().delete()
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('.enable-addon')
        assert not doc('.disable-addon')

    def test_no_listed_versions_already_disabled(self):
        # If somehow the add-on has no listed versions but is invisible, we
        # allow them to switch back to visible so that they can submit listed
        # versions.
        self.addon.versions.all().delete()
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.enable-addon')
        assert doc('.disable-addon')
        assert not doc('.enable-addon').attr('checked')
        assert not doc('.enable-addon').attr('disabled')
        assert doc('.disable-addon').attr('checked') == 'checked'
        assert not doc('.disable-addon').attr('disabled')

    def test_cancel_get(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615', 'listed'])
        assert self.client.get(cancel_url).status_code == 405

    def test_cancel_wrong_status(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615', 'listed'])
        file = self.addon.current_version.file
        for status in Addon.STATUS_CHOICES:
            if status in (amo.STATUS_NOMINATED, amo.STATUS_DELETED):
                continue
            file_status = (
                amo.STATUS_APPROVED
                if status == amo.STATUS_APPROVED
                else amo.STATUS_DISABLED
            )
            file.update(status=file_status)
            self.addon.update_status()
            if status in (amo.STATUS_DISABLED, amo.STATUS_REJECTED):
                self.addon.update(status=status)

            self.client.post(cancel_url)
            assert Addon.objects.get(id=3615).status == status

    def test_cancel(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615', 'listed'])
        self.addon.current_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        latest_version = self.addon.current_version
        assert not latest_version.is_user_disabled
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 0
        )
        self.client.post(cancel_url)
        assert Addon.objects.get(id=3615).status == amo.STATUS_NULL
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 1
        )
        assert ActivityLog.objects.filter(
            action=amo.LOG.DISABLE_VERSION.id
        ).get().arguments == [self.addon, latest_version]
        latest_version.file.reload()
        assert latest_version.is_user_disabled
        assert latest_version.file.status == amo.STATUS_DISABLED

    def test_cancel_obey_channel_listed(self):
        addon = Addon.objects.get(id=3615)
        file_ = addon.current_version.file
        file_.update(status=amo.STATUS_AWAITING_REVIEW)
        unlisted_file = version_factory(
            addon=addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        ).file
        cancel_url = reverse('devhub.addons.cancel', args=['a3615', 'listed'])
        self.client.post(cancel_url)
        file_.reload()
        assert file_.status == amo.STATUS_DISABLED
        assert file_.version.is_user_disabled
        unlisted_file.reload()
        assert not unlisted_file.version.is_user_disabled
        assert unlisted_file.status == amo.STATUS_AWAITING_REVIEW
        addon.reload()
        assert addon.status == amo.STATUS_NULL
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 1
        )
        assert ActivityLog.objects.filter(
            action=amo.LOG.DISABLE_VERSION.id
        ).get().arguments == [addon, file_.version]

    def test_cancel_obey_channel_unlisted(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        version.update(channel=amo.CHANNEL_UNLISTED)
        file_ = version.file
        file_.update(status=amo.STATUS_AWAITING_REVIEW)
        listed_file = version_factory(
            addon=addon,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        ).file
        addon.update(status=amo.STATUS_NOMINATED)
        cancel_url = reverse('devhub.addons.cancel', args=['a3615', 'unlisted'])
        self.client.post(cancel_url)
        file_.reload()
        assert file_.status == amo.STATUS_DISABLED
        assert file_.version.is_user_disabled
        listed_file.reload()
        assert not listed_file.version.is_user_disabled
        assert listed_file.status == amo.STATUS_AWAITING_REVIEW
        addon.reload()
        assert addon.status == amo.STATUS_NOMINATED
        assert (
            ActivityLog.objects.filter(action=amo.LOG.DISABLE_VERSION.id).count() == 1
        )
        assert ActivityLog.objects.filter(
            action=amo.LOG.DISABLE_VERSION.id
        ).get().arguments == [addon, file_.version]

    def test_not_cancel(self):
        self.client.logout()
        cancel_url = reverse('devhub.addons.cancel', args=['a3615', 'listed'])
        assert self.addon.status == amo.STATUS_APPROVED
        response = self.client.post(cancel_url)
        assert response.status_code == 302
        assert Addon.objects.get(id=3615).status == amo.STATUS_APPROVED

    def test_incomplete_request_review(self):
        self.addon.update(status=amo.STATUS_NULL)
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button').text()
        assert buttons == 'Request Review'

    def test_in_submission_can_request_review(self):
        self.addon.update(status=amo.STATUS_NULL)
        latest_version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        latest_version.file.update(status=amo.STATUS_DISABLED)
        version_factory(addon=self.addon, file_kw={'status': amo.STATUS_DISABLED})
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button')
        # We should only show the links for one of the disabled versions.
        assert buttons.length == 1
        assert buttons.text() == 'Request Review'

    def test_reviewed_cannot_request_review(self):
        self.addon.update(status=amo.STATUS_NULL)
        latest_version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        latest_version.file.update(
            approval_date=datetime.now(), status=amo.STATUS_DISABLED
        )
        version_factory(
            addon=self.addon,
            human_review_date=datetime.now(),
            file_kw={'status': amo.STATUS_DISABLED},
        )
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button')
        # We should only show the links for one of the disabled versions.
        assert buttons.length == 0

    def test_version_history(self):
        v1 = self.version
        v2, _ = self._extra_version_and_file(amo.STATUS_AWAITING_REVIEW)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        show_links = doc('.review-history-show')
        assert show_links.length == 2
        assert show_links[0].attrib['data-div'] == '#%s-review-history' % v1.id
        assert show_links[1].attrib['data-div'] == '#%s-review-history' % v2.id

        # Both links will have a 'data-version' attribute.
        assert show_links[0].attrib['data-version'] == str(v1.id)
        assert show_links[1].attrib['data-version'] == str(v2.id)

        # Test review history
        review_history_td = doc('#%s-review-history' % v1.id)[0]
        assert review_history_td.attrib['data-session-id'] == (
            self.client.session.session_key
        )
        api_url = absolutify(
            reverse_ns('version-reviewnotes-list', args=[self.addon.id, v1.id])
        )
        assert review_history_td.attrib['data-api-url'] == api_url
        assert doc('.review-history-hide').length == 2

        pending_activity_count = doc('.review-history-pending-count')
        # No counter, because we don't have any pending activity to show.
        assert pending_activity_count.length == 0

        # Reply box div is there for each version
        assert doc('.dev-review-reply-form').length == 2
        for idx, version in enumerate([v1, v2]):
            reply_api_url = absolutify(
                reverse_ns('version-reviewnotes-list', args=[self.addon.id, version.pk])
            )
            review_form = doc('.dev-review-reply-form')[idx]
            assert review_form.attrib['action'] == reply_api_url
            assert (
                review_form.attrib['data-session-id'] == self.client.session.session_key
            )
            assert (
                review_form.attrib['data-history'] == '#%s-review-history' % version.pk
            )
            textarea = doc('.dev-review-reply-form textarea')[idx]
            assert textarea.attrib['maxlength'] == '100000'

    def test_version_history_mixed_channels(self):
        v1 = self.version
        v2, _ = self._extra_version_and_file(amo.STATUS_AWAITING_REVIEW)
        v2.update(channel=amo.CHANNEL_UNLISTED)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        # Should be 2 reply boxes, one for each channel
        assert doc('.dev-review-reply-form').length == 2
        assert doc('.dev-review-reply-form')[0].attrib['data-history'] == (
            '#%s-review-history' % v1.id
        )
        assert doc('.dev-review-reply-form')[1].attrib['data-history'] == (
            '#%s-review-history' % v2.id
        )

    def test_pending_activity_count(self):
        v1 = self.addon.current_version
        v1.update(created=self.days_ago(1))
        v2, _ = self._extra_version_and_file(amo.STATUS_AWAITING_REVIEW)
        v3, _ = self._extra_version_and_file(amo.STATUS_APPROVED)
        # Add some activity log messages
        ActivityLog.objects.create(
            amo.LOG.REVIEWER_REPLY_VERSION, v1.addon, v1, user=self.user
        )
        ActivityLog.objects.create(
            amo.LOG.REVIEWER_REPLY_VERSION, v2.addon, v2, user=self.user
        )
        ActivityLog.objects.create(
            amo.LOG.REVIEWER_REPLY_VERSION, v2.addon, v2, user=self.user
        )

        with self.assertNumQueries(41):
            # 1. SAVEPOINT
            # 2. the add-on
            # 3. translations for that add-on (default transformer)
            # 4. categories for that add-on (default transformer)
            # 5. current version for that add-on (default transformer)
            # 6. translations for the current version (default transformer)
            # 7. applications versions for the current version (default transformer)
            # 8. users for that add-on (default transformer)
            # 9. previews for that add-on (default transformer)
            # 10. current user
            # 11. groups for that user
            # 12. check on user being an author
            # 13. count versions for the add-on for pagination
            # 14. RELEASE SAVEPOINT
            # 15. add-ons for that user
            # 16. latest version in listed channel
            # 17. translations for that version
            # 18. latest version in unlisted channel
            # 19. latest public version in listed channel
            # 20. Translations for that version
            # 21. check on user being an author (dupe)
            # 22. site notice
            # 23. suppressed email waffle switch check
            # 24. 8 latest add-ons from that user for the menu
            # 25. translations for those add-ons
            # 26. count of pending activities on latest version
            # 27. file validation for that latest version
            # 28. versions being displayed w/ pending activities count and
            #     file/validation/blockversion attached
            # 29. latest non-disabled version
            # 30. translations for that version
            # 31. are there versions in unlisted channel
            # 32. check on user being an owner
            # 33. versions in unlisted channel
            # 34. translations for those versions
            # 35. latest non-disabled version in unlisted channel
            # 36. check on user being an author (dupe)
            # 38. waffle switch
            # 39-40. promotion group queries
            # 41. (not in order) version-rollback waffle check
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        # Three versions...
        assert doc('.review-history-show').length == 3
        # ...2 have pending activities
        pending_activity_count = doc('.review-history-pending-count')
        assert pending_activity_count.length == 2
        # There are two activity logs pending on v2, one on v1.
        pending_activity_count_for_v2 = pending_activity_count[0]
        assert pending_activity_count_for_v2.text_content() == '2'
        pending_activity_count_for_v1 = pending_activity_count[1]
        assert pending_activity_count_for_v1.text_content() == '1'

    def test_channel_tag(self):
        self.addon.current_version.update(created=self.days_ago(1))
        v2, _ = self._extra_version_and_file(amo.STATUS_DISABLED)
        self.addon.versions.update(channel=amo.CHANNEL_LISTED)
        self.addon.update_version()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('td.file-status').length == 2
        # No tag shown because all listed versions
        assert doc('span.distribution-tag-listed').length == 0
        assert doc('span.distribution-tag-unlisted').length == 0

        # Make all the versions unlisted.
        self.addon.versions.update(channel=amo.CHANNEL_UNLISTED)
        self.addon.update_version()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('td.file-status').length == 2
        # No tag shown because all unlisted versions
        assert doc('span.distribution-tag-listed').length == 0
        assert doc('span.distribution-tag-unlisted').length == 0

        # Make one of the versions listed.
        v2.update(channel=amo.CHANNEL_LISTED)
        v2.file.update(status=amo.STATUS_AWAITING_REVIEW)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        file_status_tds = doc('td.file-status')
        assert file_status_tds.length == 2
        # Tag for channels are shown because both listed and unlisted versions.
        assert file_status_tds('span.distribution-tag-listed').length == 1
        assert file_status_tds('span.distribution-tag-unlisted').length == 1
        # Extra tags in the headers too
        assert doc('h3 span.distribution-tag-listed').length == 2

    @override_switch('version-rollback', active=True)
    def test_version_rollback_form_not_available(self):
        first_version = self.addon.current_version
        second_version = version_factory(addon=self.addon)
        first_version.file.update(status=amo.STATUS_DISABLED)
        assert self.addon.current_version == second_version
        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        version_factory(addon=self.addon, channel=amo.CHANNEL_UNLISTED)

        with self.assertNumQueries(45):
            # see test_pending_activity_count for the query breakdown
            # + 2 more for the 2 extra versions (not good, but the current state)
            # + 2 more for the listed and unlisted rollback queries
            response = self.client.get(self.url)
        # no versions available for rollback, so the button and form isn't available
        doc = pq(response.content)
        assert doc('a.button.version-rollback').length == 0
        assert doc('#modal-rollback-version').length == 0

    @override_switch('version-rollback', active=True)
    def test_version_rollback_form_listed_only(self):
        first_version = self.addon.current_version
        second_version = version_factory(addon=self.addon)
        assert self.addon.current_version == second_version

        # if there is a version available for rollback, the button and form are present
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('a.button.version-rollback').length == 1
        modal = doc('#modal-rollback-version')
        assert modal.length == 1
        # we hide the channel selector, because there are no other channels
        assert modal('input[name="channel"]').attr('type') == 'hidden'
        assert modal('input[name="channel"]').attr('value') == str(amo.CHANNEL_LISTED)
        assert modal('select option').length == 1
        assert modal('select option')[0].text == first_version.version
        # and the select for unlisted versions is not present
        assert 'Choose version' not in modal.html()

        assert modal(
            f'tr#listed-version-row td[data-current-version="{second_version.version}"]'
        )

    @override_switch('version-rollback', active=True)
    def test_version_rollback_form_unlisted_only(self):
        first_version = self.addon.current_version
        second_version = version_factory(addon=self.addon)
        self.make_addon_unlisted(self.addon)

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('a.button.version-rollback').length == 1
        modal = doc('#modal-rollback-version')
        assert modal.length == 1
        # similarly, we hide the channel selector, because there are no listed versions
        channel_input = modal('input[name="channel"]')
        assert channel_input.attr('type') == 'hidden'
        assert channel_input.attr('value') == str(amo.CHANNEL_UNLISTED)
        assert modal('#id_listed_version').length == 0
        assert 'Choose version' in modal.html()
        assert modal('select option').length == 2
        assert modal('select option')[0].text == 'Choose version'
        assert modal('select option')[1].text == first_version.version

        assert modal(
            'tr#unlisted-version-row '
            f'td[data-current-version="{second_version.version}"]'
        )

    @override_switch('version-rollback', active=True)
    def test_version_rollback_form_listed_but_not_appropriate(self):
        version_factory(addon=self.addon, channel=amo.CHANNEL_UNLISTED)
        version_factory(addon=self.addon, channel=amo.CHANNEL_UNLISTED)

        # with both channels available, but no appropriate listed version
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('a.button.version-rollback').length == 1
        modal = doc('#modal-rollback-version')
        assert modal.length == 1
        # this time we show the channel selector, because there are both channels
        channel_selector = 'input[name="channel"]'
        assert modal(channel_selector).attr('type') == 'radio'
        # but default to unlisted, because there are no listed versions to rollback to
        assert modal(f'{channel_selector}[value="{amo.CHANNEL_UNLISTED}"]').attr(
            'checked'
        )
        assert not modal(f'{channel_selector}[value="{amo.CHANNEL_LISTED}"]').attr(
            'checked'
        )
        # and disable it
        assert modal(f'{channel_selector}[disabled]').length == 2
        assert modal(channel_selector).length == 2
        assert modal('#id_listed_version option').length == 1
        assert (
            modal('#id_listed_version option').text()
            == 'No appropriate version available'
        )
        assert 'Choose version' in modal.html()
        assert modal('#id_unlisted_version option').length == 2

    @override_switch('version-rollback', active=True)
    def test_version_rollback_form_both_channels(self):
        listed_version = self.addon.current_version
        second_listed_version = version_factory(addon=self.addon)
        version_factory(addon=self.addon, channel=amo.CHANNEL_UNLISTED)
        second_unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )

        # with both channels available with multiple versions
        with self.assertNumQueries(47):
            # see test_pending_activity_count & test_version_rollback_form_not_available
            # for the baseline when there no versions available.  We expect 2 more
            # queries here:
            # - one to fetch the channel for the latest version created.
            # - one for the latest unlisted version.
            response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('a.button.version-rollback').length == 1
        modal = doc('#modal-rollback-version')
        assert modal.length == 1
        # this time we show the channel selector, because there are both channels
        channel_selector = 'input[name="channel"]'
        assert modal(channel_selector).attr('type') == 'radio'
        # and preselect unlisted because it's the most recent channel for a version
        assert modal(f'{channel_selector}[value="{amo.CHANNEL_UNLISTED}"]').attr(
            'checked'
        )
        assert not modal(f'{channel_selector}[value="{amo.CHANNEL_LISTED}"]').attr(
            'checked'
        )
        # and they're enabled
        assert modal(f'{channel_selector}[disabled]').length == 0
        assert modal(channel_selector).length == 2
        assert modal('#id_listed_version option').length == 1
        assert modal('#id_listed_version option').text() == listed_version.version
        assert 'Choose version' in modal.html()
        assert modal('#id_unlisted_version option').length == 2

        assert modal(
            'tr#listed-version-row '
            f'td[data-current-version="{second_listed_version.version}"]'
        )
        assert modal(
            'tr#unlisted-version-row '
            f'td[data-current-version="{second_unlisted_version.version}"]'
        )

        assert (
            modal('textarea[name="release_notes"]').val()
            == '\nAutomatic rollback based on version [m.m].'
        )

    @override_switch('version-rollback', active=True)
    def test_version_rollback_submit(self):
        first_version = self.addon.current_version
        second_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_APPROVED}
        )
        data = {
            'channel': amo.CHANNEL_LISTED,
            'listed_version': first_version.id,
            'new_version_string': second_version.version,
            'rollback-submit': '',
            'release_notes': 'release notes!',
        }
        response = self.client.post(self.url, data)
        self.assertFormError(
            response,
            'rollback_form',
            'new_version_string',
            [f'Version {data["new_version_string"]} already exists.'],
        )

        data['new_version_string'] = second_version.version + '.1'
        with mock.patch(
            'olympia.devhub.views.duplicate_addon_version_for_rollback.delay'
        ) as mock_rollback_task:
            response = self.client.post(self.url, data)
            self.assert3xx(response, self.url, 302)
            mock_rollback_task.assert_called_once_with(
                version_pk=first_version.pk,
                new_version_number=data['new_version_string'],
                user_pk=self.user.pk,
                notes={'en-us': 'release notes!'},
            )

        response = self.client.get(self.url)
        assert (
            "Rollback submitted. You'll be notified when it's approved"
            in pq(response.content).text()
        )

    @override_switch('version-rollback', active=True)
    def test_version_rollback_submit_in_other_locale(self):
        self.addon.update(default_locale='de')
        with self.activate('fr'):
            self.url = self.addon.get_dev_url('versions')
        first_version = self.addon.current_version
        second_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_APPROVED}
        )
        data = {
            'channel': amo.CHANNEL_LISTED,
            'listed_version': first_version.id,
            'new_version_string': second_version.version + '.1',
            'rollback-submit': '',
            'release_notes': 'lé release notes!',
        }

        with mock.patch(
            'olympia.devhub.views.duplicate_addon_version_for_rollback.delay'
        ) as mock_rollback_task:
            response = self.client.post(self.url, data)
            self.assert3xx(response, self.url, 302)
            mock_rollback_task.assert_called_once_with(
                version_pk=first_version.pk,
                new_version_number=data['new_version_string'],
                user_pk=self.user.pk,
                # This is not great, because release notes will be empty in the default
                # locale, but it's consistent with how the new version form works too.
                notes={'fr': 'lé release notes!', 'de': None},
            )

        response = self.client.get(self.url)
        assert (
            'Rétablissement demandé. Vous recevrez une notification une fois approuvé'
            in pq(response.content).text()
        )

    def test_new_upload_button(self):
        response = self.client.get(self.url)
        button = pq(response.content)('.version-buttons a.button.version-upload')
        assert button
        assert button.text() == 'Upload a New Version'
        assert button.attr('href') == (
            reverse('devhub.submit.version', args=[self.addon.slug])
        )

        # Do show for "Invisible" or "Rejected" add-ons (they can upload an
        # unlisted version)
        self.addon.update(status=amo.STATUS_REJECTED)
        response = self.client.get(self.url)
        button = pq(response.content)('.version-buttons a.button.version-upload')
        assert button

        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        button = pq(response.content)('.version-buttons a.button.version-upload')
        assert button

        # Don't show for STATUS_DISABLED addons.
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        button = pq(response.content)('.version-buttons a.button.version-upload')
        assert not button


class TestVersionEditBase(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.client.force_login(self.user)
        self.addon = self.get_addon()
        self.version = self.get_version()
        self.url = reverse('devhub.versions.edit', args=['a3615', self.version.id])
        create_default_webext_appversion()

    def get_addon(self):
        return Addon.objects.get(id=3615)

    def get_version(self):
        return self.get_addon().current_version

    def formset(self, *args, **kw):
        return formset(*args, **kw)


class TestVersionEditDetails(TestVersionEditBase):
    def setUp(self):
        super().setUp()
        ctx = self.client.get(self.url).context
        compat = initial(ctx['compat_form'].forms[0])
        self.initial = formset(compat)
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED
        )

    def formset(self, *args, **kw):
        return super().formset(*args, **{**self.initial, **kw})

    def test_edit_notes(self):
        data = self.formset(release_notes='xx', approval_notes='yy')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        version = self.get_version()
        assert str(version.release_notes) == 'xx'
        assert str(version.approval_notes) == 'yy'

    def test_approval_notes_and_approval_notes_too_long(self):
        data = self.formset(approval_notes='ü' * 3001, release_notes='è' * 3002)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        assert (
            response.context['version_form'].fields['approval_notes'].max_length == 3000
        )
        assert (
            response.context['version_form'].fields['approval_notes'].max_length == 3000
        )
        assert (
            response.context['version_form']
            .fields['release_notes']
            .widget.attrs['maxlength']
            == '3000'
        )
        assert (
            response.context['version_form']
            .fields['release_notes']
            .widget.attrs['maxlength']
            == '3000'
        )
        assert response.context['version_form'].errors == {
            'approval_notes': [
                'Ensure this value has at most 3000 characters (it has 3001).'
            ],
            'release_notes': [
                'Ensure this value has at most 3000 characters (it has 3002).'
            ],
        }

    def test_version_number_redirect(self):
        url = self.url.replace(str(self.version.id), self.version.version)
        response = self.client.get(url, follow=True)
        self.assert3xx(response, self.url)

    def test_version_deleted(self):
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

        data = self.formset(release_notes='xx', approval_notes='yy')
        response = self.client.post(self.url, data)
        assert response.status_code == 404

    def test_cant_upload(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('a.add-file')

    def test_add(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert response.context['compat_form'].extra_forms
        assert doc('p.add-app')[0].attrib['class'] == 'add-app'

    def test_add_not(self):
        for id in [18, 52, 59, 60, 61]:
            av = AppVersion(application=id, version='1')
            av.save()
            ApplicationsVersions(
                application=id, min=av, max=av, version=self.version
            ).save()

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not response.context['compat_form'].extra_forms
        assert doc('p.add-app')[0].attrib['class'] == 'add-app hide'

    def test_existing_source_link(self):
        with temp.NamedTemporaryFile(
            suffix='.zip', dir=temp.gettempdir()
        ) as source_file:
            with zipfile.ZipFile(source_file, 'w') as zip_file:
                zip_file.writestr('foo', 'a' * (2**21))
            source_file.seek(0)
            self.version.source.save(
                os.path.basename(source_file.name), DjangoFile(source_file)
            )
            self.version.save()

        response = self.client.get(self.url)
        doc = pq(response.content)
        link = doc('.current-source-link')
        assert link
        assert link.text() == 'View current'
        assert link[0].attrib['href'] == reverse(
            'downloads.source', args=(self.version.pk,)
        )

    def test_should_accept_zip_source_file(self):
        with temp.NamedTemporaryFile(
            suffix='.zip', dir=temp.gettempdir()
        ) as source_file:
            with zipfile.ZipFile(source_file, 'w') as zip_file:
                zip_file.writestr('foo', 'a' * (2**21))
            source_file.seek(0)
            data = self.formset(source=source_file)
            response = self.client.post(self.url, data)
        assert response.status_code == 302
        version = Version.objects.get(pk=self.version.pk)
        assert version.source
        assert version.needshumanreview_set.count() == 0

        # Check that the corresponding automatic activity log has been created.
        assert ActivityLog.objects.filter(
            action=amo.LOG.SOURCE_CODE_UPLOADED.id
        ).exists()
        log = ActivityLog.objects.get(action=amo.LOG.SOURCE_CODE_UPLOADED.id)
        assert log.user == self.user
        assert log.details is None
        assert log.arguments == [self.addon, self.version]

    def test_source_uploaded_pending_rejection_sets_needs_human_review_flag(self):
        self.version = Version.objects.get(pk=self.version.pk)
        VersionReviewerFlags.objects.create(
            version=self.version,
            pending_rejection=datetime.now() + timedelta(days=2),
            pending_rejection_by=user_factory(),
            pending_content_rejection=False,
        )
        with temp.NamedTemporaryFile(
            suffix='.zip', dir=temp.gettempdir()
        ) as source_file:
            with zipfile.ZipFile(source_file, 'w') as zip_file:
                zip_file.writestr('foo', 'a' * (2**21))
            source_file.seek(0)
            data = self.formset(source=source_file)
            response = self.client.post(self.url, data)
        assert response.status_code == 302
        self.version = Version.objects.get(pk=self.version.pk)
        assert self.version.source
        assert self.version.needshumanreview_set.filter(is_active=True).count() == 1

        # Check that the corresponding automatic activity log has been created.
        assert ActivityLog.objects.filter(
            action=amo.LOG.SOURCE_CODE_UPLOADED.id
        ).exists()
        log = ActivityLog.objects.for_versions(self.version).get(
            action=amo.LOG.SOURCE_CODE_UPLOADED.id
        )
        assert log.user == self.user
        assert log.details is None
        assert log.arguments == [self.addon, self.version]

    def test_source_field_disabled_after_human_review_no_source(self):
        self.version.update(human_review_date=datetime.now())
        response = self.client.get(self.url)
        assert b'You cannot change attached sources' in response.content
        doc = pq(response.content)
        # The file input isn't rendered
        assert not doc('#id_source')
        # There isn't a current file, so there shouldn't be a link to one
        assert not doc('.current-source-link')

        # Try to submit anyway
        with temp.NamedTemporaryFile(
            suffix='.zip', dir=temp.gettempdir()
        ) as source_file:
            with zipfile.ZipFile(source_file, 'w') as zip_file:
                zip_file.writestr('foo', 'a' * (2**21))
            source_file.seek(0)
            response = self.client.post(self.url, self.formset(source=source_file))
        version = Version.objects.get(pk=self.version.pk)
        assert not version.source

    def test_source_field_disabled_after_human_review_has_source(self):
        self.version.update(human_review_date=datetime.now())
        # This test sets source and checks the link is present
        self.test_existing_source_link()

        response = self.client.get(self.url)
        assert b'You cannot change attached sources' in response.content
        doc = pq(response.content)
        assert not doc('#id_source')

        # Try to clear anyway
        response = self.client.post(
            self.url, self.formset(**{'source': '', 'source-clear': 'on'})
        )
        assert response.status_code == 302
        assert self.version.source  # still set

    @mock.patch('olympia.devhub.views.log')
    def test_logging(self, log_mock):
        with temp.NamedTemporaryFile(
            suffix='.zip', dir=temp.gettempdir()
        ) as source_file:
            with zipfile.ZipFile(source_file, 'w') as zip_file:
                zip_file.writestr('foo', 'a' * (2**21))
            source_file.seek(0)
            data = self.formset(source=source_file)
            response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert log_mock.info.call_count == 4
        assert log_mock.info.call_args_list[0][0] == (
            'version_edit, form populated, addon.slug: %s, version.id: %s',
            self.addon.slug,
            self.version.id,
        )
        assert log_mock.info.call_args_list[1][0] == (
            'version_edit, form validated, addon.slug: %s, version.id: %s',
            self.addon.slug,
            self.version.id,
        )
        assert log_mock.info.call_args_list[2][0] == (
            'version_edit, form saved, addon.slug: %s, version.id: %s',
            self.addon.slug,
            self.version.id,
        )
        assert log_mock.info.call_args_list[3][0] == (
            'version_edit, redirecting to next view, addon.slug: %s, version.id: %s',
            self.addon.slug,
            self.version.id,
        )

    @mock.patch('olympia.devhub.views.log')
    def test_no_logging_on_initial_display(self, log_mock):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert log_mock.info.call_count == 0

    @mock.patch('olympia.devhub.views.log')
    def test_no_logging_without_source(self, log_mock):
        data = self.formset(release_notes='xx')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert log_mock.info.call_count == 0

    @mock.patch('olympia.devhub.views.log')
    def test_logging_failed_validation(self, log_mock):
        with temp.NamedTemporaryFile(
            suffix='.exe', dir=temp.gettempdir()
        ) as source_file:
            with zipfile.ZipFile(source_file, 'w') as zip_file:
                zip_file.writestr('foo', 'a' * (2**21))
            source_file.seek(0)
            data = self.formset(source=source_file)
            response = self.client.post(self.url, data)
        assert response.status_code == 200
        assert response.context['version_form'].errors == {
            'source': [
                'Unsupported file type, please upload an archive file '
                + '(.zip, .tar.gz, .tgz, .tar.bz2).'
            ]
        }
        assert log_mock.info.call_count == 2
        assert log_mock.info.call_args_list[0][0] == (
            'version_edit, form populated, addon.slug: %s, version.id: %s',
            self.addon.slug,
            self.version.id,
        )
        assert log_mock.info.call_args_list[1][0] == (
            'version_edit, validation failed, re-displaying the template, '
            + 'addon.slug: %s, version.id: %s',
            self.addon.slug,
            self.version.id,
        )

    def test_email_is_sent_to_relevant_people_for_source_code_upload(self):
        # Have a reviewer review a version.
        reviewer = user_factory()
        self.grant_permission(reviewer, 'Addons:Review')
        ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION_DELAYED, self.addon, self.version, user=reviewer
        )

        # Add an extra developer to the add-on
        extra_author = user_factory()
        self.addon.authors.add(extra_author)

        # Add someone in group meant to receive a copy of all activity emails.
        group, _ = Group.objects.get_or_create(name=ACTIVITY_MAIL_GROUP)
        staff_user = user_factory()
        staff_user.groups.add(group)

        # Have the developer upload source file for the version reviewed.
        self.test_should_accept_zip_source_file()

        # Check that an email has been sent to relevant people.
        assert len(mail.outbox) == 2
        for message in mail.outbox:
            assert message.subject == ('Mozilla Add-ons: Delicious Bookmarks 2.1.072')
            assert 'Source code uploaded' in message.body

        # Check each message was sent separately to who we are meant to notify.
        assert mail.outbox[0].to != mail.outbox[1].to
        assert set(mail.outbox[0].to + mail.outbox[1].to) == {
            extra_author.email,
            staff_user.email,
        }

    def test_should_not_accept_exe_source_file(self):
        with temp.NamedTemporaryFile(
            suffix='.exe', dir=temp.gettempdir()
        ) as source_file:
            with zipfile.ZipFile(source_file, 'w') as zip_file:
                zip_file.writestr('foo', 'a' * (2**21))
            source_file.seek(0)
            data = self.formset(source=source_file)
            response = self.client.post(self.url, data)
            assert response.status_code == 200
            assert not Version.objects.get(pk=self.version.pk).source


class TestVersionEditStaticTheme(TestVersionEditBase):
    def setUp(self):
        super().setUp()
        self.addon.update(type=amo.ADDON_STATICTHEME)

    def test_no_compat(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('#id_form-TOTAL_FORMS')

    def test_no_upload(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('a.add-file')


class TestVersionEditCompat(TestVersionEditBase):
    def get_form(self, url=None):
        if not url:
            url = self.url
        av = self.version.apps.get()
        assert av.min.version == '2.0'
        assert av.max.version == '4.0'
        form = self.client.get(url).context['compat_form'].initial_forms[0]
        return initial(form)

    def formset(self, *args, **kw):
        defaults = formset(prefix='files')
        defaults.update(kw)
        return super().formset(*args, **defaults)

    def test_add_appversion(self):
        form = self.client.get(self.url).context['compat_form'].initial_forms[0]
        data = self.formset(
            initial(form),
            {
                'application': amo.ANDROID.id,
                'min': AppVersion.objects.get(
                    application=amo.ANDROID.id,
                    version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
                ).pk,
                'max': AppVersion.objects.get(
                    application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
                ).pk,
            },
            initial_count=1,
        )
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        apps = [app.id for app in self.get_version().compatible_apps.keys()]
        assert sorted(apps) == sorted([amo.FIREFOX.id, amo.ANDROID.id])
        assert list(
            ActivityLog.objects.exclude(action=amo.LOG.LOG_IN.id).values_list('action')
        ) == ([(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_update_appversion(self):
        data = self.get_form()
        data.update(
            min=AppVersion.objects.get(
                application=amo.FIREFOX.id,
                version=amo.DEFAULT_WEBEXT_MIN_VERSION,
            ).pk,
            max=AppVersion.objects.get(
                application=amo.FIREFOX.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
            ).pk,
        )
        response = self.client.post(self.url, self.formset(data, initial_count=1))
        assert response.status_code == 302
        av = self.version.apps.get()
        assert av.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert av.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert list(
            ActivityLog.objects.exclude(action=amo.LOG.LOG_IN.id).values_list('action')
        ) == ([(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_delete_appversion(self):
        # Add android compat so we can delete firefox.
        self.test_add_appversion()
        form = self.client.get(self.url).context['compat_form']
        data = list(map(initial, form.initial_forms))
        data[0]['DELETE'] = True
        response = self.client.post(self.url, self.formset(*data, initial_count=2))
        assert response.status_code == 302
        apps = [app.id for app in self.get_version().compatible_apps.keys()]
        assert apps == [amo.ANDROID.id]
        assert list(
            ActivityLog.objects.exclude(action=amo.LOG.LOG_IN.id).values_list('action')
        ) == ([(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_cant_delete_android_if_locked_from_manifest(self):
        # Add android compat from manifest. We shouldn't be able to delete it.
        avs = self.addon.current_version.apps.create(
            application=amo.ANDROID.id,
            min=AppVersion.objects.get(
                application=amo.ANDROID.id,
                version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
            ),
            max=AppVersion.objects.get(
                application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
            ),
            originated_from=amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID,
        )
        form = self.client.get(self.url).context['compat_form']
        data = list(map(initial, form.initial_forms))
        data[1]['DELETE'] = True
        response = self.client.post(self.url, self.formset(*data, initial_count=2))
        # We've overridden add_fields() on the formset to prevent the delete
        # field from being added, so Django never adds it to the HTML and
        # silently ignores it if it's somehow part of the POST data.
        assert response.status_code == 302
        assert self.addon.current_version.apps.all().count() == 2
        avs.refresh_from_db()  # Still exists
        assert avs.min.version == amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY
        assert avs.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert (
            avs.originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
        )

    def test_cant_edit_android_if_locked_from_manifest(self):
        new_max = AppVersion.objects.create(version='122.0', application=amo.ANDROID.id)
        # Add android compat from manifest. We shouldn't be able to edit it.
        avs = self.addon.current_version.apps.create(
            application=amo.ANDROID.id,
            min=AppVersion.objects.get(
                application=amo.ANDROID.id,
                version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
            ),
            max=AppVersion.objects.get(
                application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
            ),
            originated_from=amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID,
        )
        form = self.client.get(self.url).context['compat_form']
        data = list(map(initial, form.initial_forms))
        data[1]['max'] = new_max.pk
        response = self.client.post(self.url, self.formset(*data, initial_count=2))
        # The fields for the locked applicationsversions are disabled at the
        # form level, so they would be rendered disabled in the HTML, clients
        # will never submit any edits, and Django will silently prevent any
        # changes.
        assert response.status_code == 302
        assert self.addon.current_version.apps.all().count() == 2
        avs.refresh_from_db()
        assert avs.min.version == amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY
        assert avs.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert (
            avs.originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
        )

    def test_can_submit_other_changes_when_android_compat_is_locked_from_manifest(self):
        # Add android compat from manifest. We shouldn't be able to edit it,
        # but we can still change the Firefox one.
        avs = self.addon.current_version.apps.all().get()
        self.addon.current_version.apps.create(
            application=amo.ANDROID.id,
            min=AppVersion.objects.get(
                application=amo.ANDROID.id,
                version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
            ),
            max=AppVersion.objects.get(
                application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
            ),
            originated_from=amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID,
        )
        form = self.client.get(self.url).context['compat_form']
        data = list(map(initial, form.initial_forms))
        # Change Firefox compat
        data[0]['min'] = AppVersion.objects.get(
            application=amo.FIREFOX.id,
            version=amo.DEFAULT_WEBEXT_MIN_VERSION,
        ).pk
        data[0]['max'] = AppVersion.objects.get(
            application=amo.FIREFOX.id,
            version=amo.DEFAULT_WEBEXT_MAX_VERSION,
        ).pk
        response = self.client.post(self.url, self.formset(*data, initial_count=2))
        assert response.status_code == 302
        assert self.addon.current_version.apps.all().count() == 2
        avs.refresh_from_db()
        assert avs.application == amo.FIREFOX.id
        assert avs.min.version == amo.DEFAULT_WEBEXT_MIN_VERSION
        assert avs.max.version == amo.DEFAULT_WEBEXT_MAX_VERSION
        assert avs.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_DEVELOPER

    def test_no_compat_changes(self):
        avs = self.addon.current_version.apps.all().get()
        form = self.client.get(self.url).context['compat_form']
        data = list(map(initial, form.initial_forms))
        response = self.client.post(self.url, self.formset(*data, initial_count=2))
        assert response.status_code == 302
        assert self.addon.current_version.apps.all().count() == 1
        avs.refresh_from_db()
        assert avs.originated_from == amo.APPVERSIONS_ORIGINATED_FROM_UNKNOWN

    def test_unique_apps(self):
        form = self.client.get(self.url).context['compat_form'].initial_forms[0]
        dupe = initial(form)
        del dupe['id']
        data = self.formset(initial(form), dupe, initial_count=1)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        # Because of how formsets work, the second form is expected to be a
        # tbird version range.  We got an error, so we're good.

    def test_require_appversion(self):
        old_av = self.version.apps.get()
        form = self.client.get(self.url).context['compat_form'].initial_forms[0]
        data = initial(form)
        data['DELETE'] = True
        response = self.client.post(self.url, self.formset(data, initial_count=1))
        assert response.status_code == 200

        compat_formset = response.context['compat_form']
        assert compat_formset.non_form_errors() == (
            ['Need at least one compatible application.']
        )
        assert self.version.apps.get() == old_av

        # Make sure the user can re-submit again from the page showing the
        # validation error: we should display all previously present compat
        # forms, with the DELETE bit off.
        assert compat_formset.data == compat_formset.forms[0].data
        assert compat_formset.forms[0]['DELETE'].value() is False

    def test_proper_min_max(self):
        form = self.client.get(self.url).context['compat_form'].initial_forms[0]
        data = initial(form)
        data['min'], data['max'] = data['max'], data['min']
        response = self.client.post(self.url, self.formset(data, initial_count=1))
        assert response.status_code == 200
        assert response.context['compat_form'].forms[0].non_field_errors() == (
            ['Invalid version range.']
        )

    def test_same_min_max(self):
        form = self.client.get(self.url).context['compat_form'].initial_forms[0]
        data = initial(form)
        data['max'] = data['min']
        response = self.client.post(self.url, self.formset(data, initial_count=1))
        assert response.status_code == 302
        av = self.version.apps.all()[0]
        assert av.min == av.max

    def test_statictheme_no_compat_edit(self):
        """static themes don't allow users to overwrite compat data."""
        addon = self.get_addon()
        addon.update(type=amo.ADDON_STATICTHEME)
