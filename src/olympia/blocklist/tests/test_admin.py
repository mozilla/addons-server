import json
import uuid
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.test.utils import override_settings
from django.urls import reverse

import responses
import time_machine
from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.abuse.models import ContentDecision
from olympia.activity.models import ActivityLog
from olympia.addons.models import DeniedGuid
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    collection_factory,  # Added collection_factory
    user_factory,
    version_factory,
)
from olympia.reviewers.models import NeedsHumanReview

from ..models import Block, BlocklistSubmission, BlockType


FANCY_QUOTE_OPEN = '“'
FANCY_QUOTE_CLOSE = '”'
LONG_DASH = '—'


class TestBlockAdmin(TestCase):
    def setUp(self):
        self.admin_home_url = reverse('admin:index')
        self.list_url = reverse('admin:blocklist_block_changelist')
        self.add_url = reverse('admin:blocklist_block_add')
        self.submission_url = reverse('admin:blocklist_blocklistsubmission_add')

    def test_can_see_addon_module_in_admin_with_review_admin(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert modules == ['Blocklist']

    def test_can_not_see_addon_module_in_admin_without_permissions(self):
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert modules == []

    def test_can_list(self):
        addon = addon_factory()
        block_factory(guid=addon.guid, updated_by=user_factory())
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')

    def test_can_not_list_without_permission(self):
        addon = addon_factory()
        block_factory(guid=addon.guid, updated_by=user_factory())
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 403
        assert addon.guid not in response.content.decode('utf-8')

    def test_add(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        response = self.client.get(self.add_url, follow=True)
        assert b'Add-on GUIDs (one per line)' in response.content

        # Submit an empty list of guids should redirect back to the page
        response = self.client.post(self.add_url, {'guids': ''}, follow=False)
        assert b'Add-on GUIDs (one per line)' in response.content

        # A single invalid guid should redirect back to the page too (for now)
        response = self.client.post(self.add_url, {'guids': 'guid@'}, follow=False)
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'Add-on with GUID guid@ does not exist' in response.content

        addon_factory(guid='guid@')
        # But should continue to the django admin add page if it exists
        response = self.client.post(self.add_url, {'guids': 'guid@'}, follow=True)
        self.assertRedirects(response, self.submission_url, status_code=307)

        # Multiple guids are redirected to the multiple guid view
        response = self.client.post(
            self.add_url, {'guids': 'guid@\nfoo@baa'}, follow=True
        )
        self.assertRedirects(response, self.submission_url, status_code=307)

    def test_add_from_addon_pk_view(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon = addon_factory(version_kw={'version': '123.456'})
        version = addon.current_version
        second_version = version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)
        third_version = version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)
        block_factory(addon=addon, version_ids=[third_version.id], updated_by=user)

        url = reverse('admin:blocklist_block_addaddon', args=(addon.id,))
        response = self.client.post(url, follow=True)
        self.assertRedirects(response, self.submission_url + f'?guids={addon.guid}')

        # if (for some reason) we're passed a previous, deleted, addon
        # instance, we still correctly passed along the guid.
        deleted_addon = addon_factory(status=amo.STATUS_DELETED)
        deleted_addon.addonguid.update(guid=addon.guid)
        url = reverse('admin:blocklist_block_addaddon', args=(deleted_addon.id,))
        response = self.client.post(url, follow=True)
        self.assertRedirects(response, self.submission_url + f'?guids={addon.guid}')

        # And version ids are passed along
        response = self.client.post(
            url + f'?v={version.pk}&v={second_version.pk}', follow=True
        )
        self.assertRedirects(
            response,
            self.submission_url
            + f'?guids={addon.guid}&v={version.id}&v={second_version.id}',
        )
        assert not response.context['messages']

        # Pending blocksubmissions and blocked versions are forwarded with a warning
        BlocklistSubmission.objects.create(
            input_guids=addon.guid, changed_version_ids=[version.pk]
        )
        response = self.client.post(
            url + f'?v={version.pk}&v={second_version.pk}&v={third_version.pk}',
            follow=True,
        )
        self.assertRedirects(
            response,
            self.submission_url
            + f'?guids={addon.guid}'
            + f'&v={version.id}&v={second_version.id}&v={third_version.id}',
        )
        assert [msg.message for msg in response.context['messages']] == [
            f'The version id:{version.id} could not be selected because this version '
            'is part of a pending submission',
            f'The version id:{third_version.id} could not be selected because this '
            'version is already blocked',
        ]

    def test_guid_redirects(self):
        block = block_factory(guid='foo@baa', updated_by=user_factory())
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        response = self.client.post(
            reverse('admin:blocklist_block_change', args=(block.guid,)), follow=True
        )
        self.assertRedirects(
            response,
            reverse('admin:blocklist_block_change', args=(block.pk,)),
            status_code=301,
        )

    def test_view_versions(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon = addon_factory(version_kw={'version': '1.0'})
        second_version = version_factory(addon=addon, version='2.0')
        third_version = version_factory(addon=addon, version='3.0')
        block = block_factory(
            addon=addon,
            version_ids=[second_version.id, third_version.id],
            updated_by=user,
        )
        # Make one of the blocks soft.
        block.blockversion_set.get(version=third_version).update(
            block_type=BlockType.SOFT_BLOCKED
        )

        response = self.client.get(
            reverse('admin:blocklist_block_change', args=(block.id,)),
        )
        assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert doc('.field-blocked_versions').text() == (
            'Blocked versions:\n2.0 (🛑 Hard-Blocked), 3.0 (⚠️ Soft-Blocked)'
        )

    def test_soften_harden(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon = addon_factory(version_kw={'version': '1.0'})
        second_version = version_factory(addon=addon, version='2.0')
        third_version = version_factory(addon=addon, version='3.0')
        block = block_factory(
            addon=addon,
            version_ids=[second_version.id, third_version.id],
            updated_by=user,
        )
        # Make one of the blocks soft.
        block.blockversion_set.get(version=third_version).update(
            block_type=BlockType.SOFT_BLOCKED
        )

        response = self.client.get(
            reverse('admin:blocklist_block_change', args=(block.id,)),
        )
        assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert doc('.softenlink').attr('href') == (
            reverse('admin:blocklist_blocklistsubmission_add')
            + f'?guids={addon.guid}&action={BlocklistSubmission.ACTIONS.SOFTEN}'
        )
        assert doc('.hardenlink').attr('href') == (
            reverse('admin:blocklist_blocklistsubmission_add')
            + f'?guids={addon.guid}&action={BlocklistSubmission.ACTIONS.HARDEN}'
        )
        assert 'disabled' not in doc('.hardenlink').attr('class')
        assert 'disabled' not in doc('.softenlink').attr('class')

    def test_harden_disabled_only_hard_blocked_versions_already(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon = addon_factory(version_kw={'version': '1.0'})
        second_version = version_factory(addon=addon, version='2.0')
        third_version = version_factory(addon=addon, version='3.0')
        block = block_factory(
            addon=addon,
            version_ids=[second_version.id, third_version.id],
            updated_by=user,
        )

        response = self.client.get(
            reverse('admin:blocklist_block_change', args=(block.id,)),
        )
        assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert 'disabled' in doc('.hardenlink').attr('class')
        assert 'disabled' not in doc('.softenlink').attr('class')

    def test_soften_disabled_only_soft_blocked_versions_already(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon = addon_factory(version_kw={'version': '1.0'})
        second_version = version_factory(addon=addon, version='2.0')
        third_version = version_factory(addon=addon, version='3.0')
        block = block_factory(
            addon=addon,
            version_ids=[second_version.id, third_version.id],
            updated_by=user,
            block_type=BlockType.SOFT_BLOCKED,
        )

        response = self.client.get(
            reverse('admin:blocklist_block_change', args=(block.id,)),
        )
        assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert 'disabled' not in doc('.hardenlink').attr('class')
        assert 'disabled' in doc('.softenlink').attr('class')

    def _test_upload_mlbf_disabled(self):
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        response = self.client.post(
            reverse('admin:blocklist_block_upload_mlbf'), follow=True
        )
        assert response.status_code == 403

    def test_upload_mlbf_disabled(self):
        self._test_upload_mlbf_disabled()

    @override_switch('blocklist_mlbf_submit', active=True)
    @override_settings(ENABLE_ADMIN_MLBF_UPLOAD=False)
    def test_upload_mlbf_disabled_setting(self):
        self._test_upload_mlbf_disabled()

    @override_switch('blocklist_mlbf_submit', active=False)
    @override_settings(ENABLE_ADMIN_MLBF_UPLOAD=True)
    def test_upload_mlbf_disabled_switch(self):
        self._test_upload_mlbf_disabled()

    @override_switch('blocklist_mlbf_submit', active=True)
    @override_settings(ENABLE_ADMIN_MLBF_UPLOAD=True)
    def test_upload_mlbf_disabled_permission(self):
        self._test_upload_mlbf_disabled()

    @override_switch('blocklist_mlbf_submit', active=True)
    @override_settings(ENABLE_ADMIN_MLBF_UPLOAD=True)
    def test_upload_mlf_get_request_not_allowed(self):
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(
            reverse('admin:blocklist_block_upload_mlbf'), follow=True
        )
        assert response.status_code == 405

    def _test_upload_mlbf_enabled(self, mock_upload, force_base=False):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)
        url = reverse('admin:blocklist_block_upload_mlbf')
        if force_base:
            url += '?force_base=true'
        response = self.client.post(url, follow=True)
        assert response.status_code == 200
        assert mock_upload.called
        assert mock_upload.call_args == mock.call(force_base=force_base)
        messages = list(response.context['messages'])
        assert len(messages) == 1
        assert str(messages[0]) == (
            'MLBF upload to remote settings has been triggered.'
        )

    @override_switch('blocklist_mlbf_submit', active=True)
    @override_settings(ENABLE_ADMIN_MLBF_UPLOAD=True)
    @mock.patch('olympia.blocklist.tasks.upload_mlbf_to_remote_settings_task.delay')
    def test_upload_mlbf_enabled(self, mock_upload):
        self._test_upload_mlbf_enabled(mock_upload, force_base=False)

    @override_switch('blocklist_mlbf_submit', active=True)
    @override_settings(ENABLE_ADMIN_MLBF_UPLOAD=True)
    @mock.patch('olympia.blocklist.tasks.upload_mlbf_to_remote_settings_task.delay')
    def test_upload_mlbf_enabled_force_base(self, mock_upload):
        self._test_upload_mlbf_enabled(mock_upload, force_base=True)


def check_checkbox(checkbox, version):
    assert checkbox.attrib['value'] == str(version.id)
    assert checkbox.value == str(version.id)
    assert checkbox.checked
    assert 'disabled' not in checkbox.attrib


class TestBlocklistSubmissionAdmin(TestCase):
    def setUp(self):
        self.submission_url = reverse('admin:blocklist_blocklistsubmission_add')
        self.submission_list_url = reverse(
            'admin:blocklist_blocklistsubmission_changelist'
        )
        self.task_user = user_factory(id=settings.TASK_USER_ID, display_name='Mozilla')
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )

    def test_initial_values_from_add_from_addon_pk_view(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon = addon_factory(guid='guid@')
        ver = addon.current_version
        # being deleted shouldn't affect it's inclusion in the choices
        ver_deleted = version_factory(
            addon=addon,
            channel=amo.CHANNEL_UNLISTED,
            deleted=True,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        ver_unlisted = version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)
        # these next two versions shouldn't be possible choices
        ver_add_subm = version_factory(addon=addon)
        BlocklistSubmission.objects.create(
            input_guids=addon.guid, changed_version_ids=[ver_add_subm.id]
        )
        ver_block = version_factory(addon=addon)
        block_factory(addon=addon, version_ids=[ver_block.id], updated_by=user)
        response = self.client.get(
            self.submission_url
            + f'?guids={addon.guid}&v={ver.pk}&v={ver_deleted.pk}&v={ver_add_subm.id}'
            + f'&v={ver_block.id}'
        )
        # all the `v` values are passed to initial
        assert response.context['adminform'].form.initial == {
            'input_guids': addon.guid,
            'changed_version_ids': [
                ver.id,
                ver_deleted.id,
                ver_add_subm.id,
                ver_block.id,
            ],
        }
        # but the form logic filters out the invalid choices, even when in `initial`
        assert response.context['adminform'].form.fields[
            'changed_version_ids'
        ].choices == [
            (
                addon.guid,
                [
                    (ver.id, ver.version),
                    (ver_deleted.id, ver_deleted.version),
                    (ver_unlisted.id, ver_unlisted.version),
                ],
            )
        ]
        doc = pq(response.content)
        # the selected choices are checked
        assert (
            doc(f'input[name="changed_version_ids"][value="{ver.id}"]').attr('checked')
            == 'checked'
        )
        assert (
            doc(f'input[name="changed_version_ids"][value="{ver_deleted.id}"]').attr(
                'checked'
            )
            == 'checked'
        )
        # and other one is not.
        assert (
            doc(f'input[name="changed_version_ids"][value="{ver_unlisted.id}"]').attr(
                'checked'
            )
            is None
        )

    def test_version_checkboxes(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon = addon_factory(guid='guid@', average_daily_users=100)
        ver = addon.current_version
        # being deleted shouldn't affect it's status
        ver_deleted = version_factory(
            addon=addon,
            channel=amo.CHANNEL_UNLISTED,
            deleted=True,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        # these next three versions shouldn't be possible choices
        ver_add_subm = version_factory(addon=addon)
        add_submission = BlocklistSubmission.objects.create(
            input_guids=addon.guid, changed_version_ids=[ver_add_subm.id]
        )
        ver_other = addon_factory(average_daily_users=99).current_version
        ver_block = version_factory(addon=ver_other.addon)
        ver_soft_block = version_factory(addon=ver_other.addon)
        block_factory(
            addon=addon, version_ids=[ver_block.id, ver_soft_block.id], updated_by=user
        )
        ver_soft_block.blockversion.update(block_type=BlockType.SOFT_BLOCKED)

        response = self.client.get(
            self.submission_url,
            {'guids': f'{addon.guid}\n {ver_block.addon.guid}\n'},
        )
        doc = pq(response.content.decode('utf-8'))
        checkboxes = doc('input[name=changed_version_ids]')

        assert len(checkboxes) == 3
        check_checkbox(checkboxes[0], ver)
        check_checkbox(checkboxes[1], ver_deleted)
        check_checkbox(checkboxes[2], ver_other)

        # not a checkbox because already part of a submission, green circle
        # because not blocked yet technically.
        assert doc(f'li[data-version-id="{ver_add_subm.id}"]').text() == (
            f'{ver_add_subm.version} (🟢 Not Blocked) [Edit Submission]'
        )
        submission_link = doc(f'li[data-version-id="{ver_add_subm.id}"] a')
        assert submission_link.text() == 'Edit Submission'
        assert submission_link.attr['href'] == reverse(
            'admin:blocklist_blocklistsubmission_change',
            args=(add_submission.id,),
        )

        # not a checkbox because blocked already and this is an add action
        assert doc(f'li[data-version-id="{ver_block.id}"]').text() == (
            f'{ver_block.version} (🛑 Hard-Blocked)'
        )

        # not a checkbox because (soft-)blocked already and this is an add action
        assert doc(f'li[data-version-id="{ver_soft_block.id}"]').text() == (
            f'{ver_soft_block.version} (⚠️ Soft-Blocked)'
        )

        # Now with an existing submission
        submission = BlocklistSubmission.objects.create(
            input_guids=f'{addon.guid}\n {ver_block.addon.guid}\n',
            changed_version_ids=[ver_deleted.id, ver_other.id],
        )
        response = self.client.get(
            reverse(
                'admin:blocklist_blocklistsubmission_change', args=(submission.id,)
            ),
        )
        doc = pq(response.content)
        checkboxes = doc('input[name=changed_version_ids]')
        assert len(checkboxes) == 2
        check_checkbox(checkboxes[0], ver_deleted)
        check_checkbox(checkboxes[1], ver_other)

    def test_version_checkboxes_hardening_action(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon = addon_factory(guid='guid@', average_daily_users=100)
        version_factory(
            addon=addon,
            channel=amo.CHANNEL_UNLISTED,
            deleted=True,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        # these next three versions shouldn't be possible choices
        ver_add_subm = version_factory(addon=addon)
        add_submission = BlocklistSubmission.objects.create(
            input_guids=addon.guid, changed_version_ids=[ver_add_subm.id]
        )
        ver_other = addon_factory(average_daily_users=99).current_version
        ver_block = version_factory(addon=ver_other.addon)
        ver_soft_block = version_factory(addon=ver_other.addon)
        block_factory(
            addon=addon, version_ids=[ver_block.id, ver_soft_block.id], updated_by=user
        )
        ver_soft_block.blockversion.update(block_type=BlockType.SOFT_BLOCKED)

        response = self.client.get(
            self.submission_url,
            {
                'guids': f'{addon.guid}\n {ver_block.addon.guid}\n',
                'action': BlocklistSubmission.ACTIONS.HARDEN,
            },
        )
        doc = pq(response.content.decode('utf-8'))
        checkboxes = doc('input[name=changed_version_ids]')

        assert len(checkboxes) == 1
        check_checkbox(checkboxes[0], ver_soft_block)

        # not a checkbox because already part of a submission, green circle
        # because not blocked yet technically.
        assert doc(f'li[data-version-id="{ver_add_subm.id}"]').text() == (
            f'{ver_add_subm.version} (🟢 Not Blocked) [Edit Submission]'
        )
        submission_link = doc(f'li[data-version-id="{ver_add_subm.id}"] a')
        assert submission_link.text() == 'Edit Submission'
        assert submission_link.attr['href'] == reverse(
            'admin:blocklist_blocklistsubmission_change',
            args=(add_submission.id,),
        )

        # not a checkbox because hard-blocked already and this is an harden
        # action
        assert doc(f'li[data-version-id="{ver_block.id}"]').text() == (
            f'{ver_block.version} (🛑 Hard-Blocked)'
        )

    def test_version_checkboxes_softening_action(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon = addon_factory(guid='guid@', average_daily_users=100)
        version_factory(
            addon=addon,
            channel=amo.CHANNEL_UNLISTED,
            deleted=True,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        # these next three versions shouldn't be possible choices
        ver_add_subm = version_factory(addon=addon)
        add_submission = BlocklistSubmission.objects.create(
            input_guids=addon.guid, changed_version_ids=[ver_add_subm.id]
        )
        ver_other = addon_factory(average_daily_users=99).current_version
        ver_block = version_factory(addon=ver_other.addon)
        ver_soft_block = version_factory(addon=ver_other.addon)
        block_factory(
            addon=addon, version_ids=[ver_block.id, ver_soft_block.id], updated_by=user
        )
        ver_soft_block.blockversion.update(block_type=BlockType.SOFT_BLOCKED)

        response = self.client.get(
            self.submission_url,
            {
                'guids': f'{addon.guid}\n {ver_block.addon.guid}\n',
                'action': BlocklistSubmission.ACTIONS.SOFTEN,
            },
        )
        doc = pq(response.content.decode('utf-8'))
        checkboxes = doc('input[name=changed_version_ids]')

        assert len(checkboxes) == 1
        check_checkbox(checkboxes[0], ver_block)

        # not a checkbox because already part of a submission, green circle
        # because not blocked yet technically.
        assert doc(f'li[data-version-id="{ver_add_subm.id}"]').text() == (
            f'{ver_add_subm.version} (🟢 Not Blocked) [Edit Submission]'
        )
        submission_link = doc(f'li[data-version-id="{ver_add_subm.id}"] a')
        assert submission_link.text() == 'Edit Submission'
        assert submission_link.attr['href'] == reverse(
            'admin:blocklist_blocklistsubmission_change',
            args=(add_submission.id,),
        )

        # not a checkbox because soft-blocked already and this is an soften
        # action
        assert doc(f'li[data-version-id="{ver_soft_block.id}"]').text() == (
            f'{ver_soft_block.version} (⚠️ Soft-Blocked)'
        )

    def test_add_single(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        deleted_addon = addon_factory(version_kw={'version': '1.2.5'})
        deleted_addon_version = deleted_addon.current_version
        NeedsHumanReview.objects.create(version=deleted_addon_version)
        deleted_addon.update(status=amo.STATUS_DELETED)
        deleted_addon_version.update(deleted=True)
        deleted_addon.addonguid.update(guid='guid@')
        addon = addon_factory(
            guid='guid@', name='Danger Danger', version_kw={'version': '1.2a'}
        )
        first_version = addon.current_version
        disabled_version = version_factory(
            addon=addon,
            version='2.5',
            file_kw={'status': amo.STATUS_DISABLED},
        )
        NeedsHumanReview.objects.create(version=disabled_version)
        deleted_version = version_factory(
            addon=addon,
            version='2.5.1',
            deleted=True,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        NeedsHumanReview.objects.create(version=deleted_version)
        second_version = version_factory(addon=addon, version='3')
        pending_version = version_factory(
            addon=addon, version='5.999', file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        # Delete any ActivityLog caused by our creations above to make things
        # easier to test.
        ActivityLog.objects.all().delete()

        response = self.client.get(self.submission_url + '?guids=guid@', follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert f'{addon.average_daily_users} users' in content
        assert Block.objects.count() == 0  # Check we didn't create it already
        assert 'Block History' in content

        changed_versions = [
            deleted_addon_version,
            first_version,
            disabled_version,
            deleted_version,
            second_version,
        ]
        changed_version_ids = [v.id for v in changed_versions]
        changed_version_strs = sorted(v.version for v in changed_versions)

        # Create the block
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': 'guid@',
                'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
                'block_type': BlockType.BLOCKED,
                'changed_version_ids': changed_version_ids,
                'url': 'dfd',
                'reason': 'some reason',
                'update_url_value': True,
                'update_reason_value': True,
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert Block.objects.count() == 1
        block = Block.objects.first()
        assert block.addon == addon
        assert block.updated_by == user
        # Multiple versions rejection somehow forces us to go through multiple
        # add-on status updates, it all turns out to be ok in the end though...
        logs = ActivityLog.objects.for_addons(addon)
        assert len(logs) == 5
        assert logs[0].action == amo.LOG.CHANGE_STATUS.id
        assert logs[1].action == amo.LOG.CHANGE_STATUS.id
        assert logs[2].action == amo.LOG.CHANGE_STATUS.id
        reject_log = logs[3]
        assert reject_log.action == amo.LOG.REJECT_VERSION.id
        block_log = logs[4]
        assert block_log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert block_log.arguments == [addon, addon.guid, block]
        assert block_log.details['blocked_versions'] == changed_version_strs
        assert block_log.details['added_versions'] == changed_version_strs
        assert block_log.details['reason'] == 'some reason'
        assert block_log.details['block_type'] == BlockType.BLOCKED
        assert block_log == (
            ActivityLog.objects.for_block(block).filter(action=block_log.action).get()
        )
        assert block_log == (
            ActivityLog.objects.for_guidblock('guid@')
            .filter(action=block_log.action)
            .get()
        )
        # The Reject and version blocked activities are recorded once for all affected
        # versions and attached to each of them through VersionLog.
        for version in (first_version, second_version):
            version_reject_log, version_block_log = tuple(
                ActivityLog.objects.for_versions(version)
            )
            assert version_reject_log == reject_log
            assert version_reject_log.user == user
            assert version_block_log.action == amo.LOG.BLOCKLIST_VERSION_BLOCKED.id
            assert version_block_log.arguments == [*changed_versions, block]

        # The disabled and deleted versions should only have the block activity,
        # not a reject activity
        for version in (deleted_addon_version, disabled_version):
            (version_block_log,) = tuple(ActivityLog.objects.for_versions(version))
            assert version_block_log.action == amo.LOG.BLOCKLIST_VERSION_BLOCKED.id
            assert version_block_log.arguments == [*changed_versions, block]

        assert not ActivityLog.objects.for_versions(pending_version).exists()
        change_url = reverse(
            'admin:blocklist_blocklistsubmission_change',
            args=(BlocklistSubmission.objects.last().id,),
        )
        assert [msg.message for msg in response.context['messages']] == [
            f'The blocklist submission {FANCY_QUOTE_OPEN}'
            f'<a href="{change_url}">Auto Sign-off: guid@; dfd; some reason</a>'
            f'{FANCY_QUOTE_CLOSE} was added successfully.'
        ]

        response = self.client.get(
            reverse('admin:blocklist_block_change', args=(block.pk,))
        )
        content = response.content.decode('utf-8')
        todaysdate = datetime.now().date()
        assert f'<a href="dfd">{todaysdate}</a>' in content
        assert f'Block added by {user.name}:\n        guid@' in content
        assert f'versions hard-blocked [{", ".join(changed_version_strs)}].' in content

        addon.reload()
        for version in [
            first_version,
            second_version,
            pending_version,
            disabled_version,
            deleted_version,
        ]:
            version.reload()
            version.file.reload()

        assert addon.status != amo.STATUS_DISABLED  # not 0 - * so no change
        assert first_version.file.status == amo.STATUS_DISABLED
        self.assertCloseToNow(first_version.human_review_date)
        assert second_version.file.status == amo.STATUS_DISABLED
        self.assertCloseToNow(second_version.human_review_date)
        assert pending_version.file.status == (
            amo.STATUS_AWAITING_REVIEW
        )  # no change because not in Block
        assert not pending_version.human_review_date  # no change
        assert disabled_version.file.status == amo.STATUS_DISABLED  # no change
        assert not disabled_version.human_review_date  # no change
        assert deleted_version.file.status == amo.STATUS_DISABLED  # no change
        assert not deleted_version.human_review_date  # no change
        disabled_version.reload()
        deleted_version.reload()
        deleted_addon_version.reload()
        assert not disabled_version.needshumanreview_set.filter(is_active=True).exists()
        assert not deleted_version.needshumanreview_set.filter(is_active=True).exists()
        assert not deleted_addon_version.needshumanreview_set.filter(
            is_active=True
        ).exists()

    def test_add_multiple_from_pks(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        new_addon_adu = addon_adu = 45768
        new_addon = addon_factory(
            guid='any@new', name='New Danger', average_daily_users=new_addon_adu
        )
        existing_and_complete = block_factory(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            # addon will have a different adu
            average_daily_users_snapshot=346733434,
            updated_by=user_factory(),
        )
        partial_addon_adu = addon_adu - 1
        partial_addon = addon_factory(
            guid='partial@existing',
            name='Partial Danger',
            average_daily_users=(partial_addon_adu),
        )
        partial_addon.current_version.update(
            created=partial_addon.current_version.created - timedelta(seconds=1)
        )
        block_factory(
            guid=partial_addon.guid,
            # should be updated to addon's adu
            average_daily_users_snapshot=146722437,
            updated_by=user_factory(),
        )
        new_partial_addon_version = version_factory(addon=partial_addon)
        # Delete any ActivityLog caused by our creations above to make things
        # easier to test.
        ActivityLog.objects.all().delete()

        parameter = '?addons=' + '~'.join(
            map(
                str,
                [
                    new_addon.pk,
                    existing_and_complete.addon.pk,
                    partial_addon.pk,
                    partial_addon.pk + 42,  # Invalid, ignored
                ],
            )
        )

        response = self.client.get(
            self.submission_url + parameter,
            follow=True,
        )
        content = response.content.decode('utf-8')
        # meta data for new blocks and existing ones needing update:
        assert 'Add-on GUIDs (one per line)' not in content
        total_adu = new_addon_adu + partial_addon_adu
        assert f'2 Add-on GUIDs with {total_adu:,} users:' in content
        assert 'any@new' in content
        assert 'New Danger' in content
        assert f'{new_addon.average_daily_users} users' in content
        assert 'partial@existing' in content
        assert 'Partial Danger' in content
        assert f'{partial_addon.average_daily_users} users' in content
        # but not for existing blocks already 0 - *
        assert 'full@existing' in content
        assert 'Full Danger' not in content
        assert f'{existing_and_complete.addon.average_daily_users} users' not in content

        # Check we didn't create the block already
        assert Block.objects.count() == 2
        assert BlocklistSubmission.objects.count() == 0

        # Check what's in the form we would be submitting
        doc = pq(response.content)
        assert doc('input[name=input_guids]')[0].attrib['value'].split('\n') == [
            'any@new',
            'full@existing',
            'partial@existing',
        ]
        changed_version_ids = doc('input[name=changed_version_ids]')
        assert len(changed_version_ids) == 2
        assert changed_version_ids[0].attrib['value'] == str(
            new_addon.current_version.pk
        )
        assert changed_version_ids[1].attrib['value'] == str(
            new_partial_addon_version.pk
        )

    def _test_add_multiple_submit(self, addon_adu, delay=0):
        """addon_adu is important because whether dual signoff is needed is
        based on what the average_daily_users is."""
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        new_addon_adu = addon_adu
        new_addon = addon_factory(
            guid='any@new', name='New Danger', average_daily_users=new_addon_adu
        )
        existing_and_complete = block_factory(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            # addon will have a different adu
            average_daily_users_snapshot=346733434,
            updated_by=user_factory(),
        )
        partial_addon_adu = addon_adu - 1
        partial_addon = addon_factory(
            guid='partial@existing',
            name='Partial Danger',
            average_daily_users=(partial_addon_adu),
        )
        partial_addon.current_version.update(
            created=partial_addon.current_version.created - timedelta(seconds=1)
        )
        existing_and_partial = block_factory(
            guid=partial_addon.guid,
            # should be updated to addon's adu
            average_daily_users_snapshot=146722437,
            updated_by=user_factory(),
        )
        version_factory(addon=partial_addon)
        # Delete any ActivityLog caused by our creations above to make things
        # easier to test.
        ActivityLog.objects.all().delete()

        response = self.client.post(
            self.submission_url,
            {'guids': 'any@new\npartial@existing\nfull@existing\ninvalid@'},
            follow=True,
        )
        content = response.content.decode('utf-8')
        # meta data for new blocks and existing ones needing update:
        assert 'Add-on GUIDs (one per line)' not in content
        total_adu = new_addon_adu + partial_addon_adu
        assert f'2 Add-on GUIDs with {total_adu:,} users:' in content
        assert 'any@new' in content
        assert 'New Danger' in content
        assert f'{new_addon.average_daily_users} users' in content
        assert 'partial@existing' in content
        assert 'Partial Danger' in content
        assert f'{partial_addon.average_daily_users} users' in content
        # but not for existing blocks already 0 - *
        assert 'full@existing' in content
        assert 'Full Danger' not in content
        assert f'{existing_and_complete.addon.average_daily_users} users' not in content
        # no metadata for an invalid guid but it should be shown
        assert 'invalid@' in content
        # Check we didn't create the block already
        assert Block.objects.count() == 2
        assert BlocklistSubmission.objects.count() == 0

        # Create the block submission
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': ('any@new\npartial@existing\nfull@existing\ninvalid@'),
                'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
                'block_type': BlockType.BLOCKED,
                'changed_version_ids': [
                    new_addon.current_version.id,
                    partial_addon.current_version.id,
                ],
                'disable_addon': True,
                'url': 'dfd',
                'reason': 'some reason',
                'update_url_value': True,
                'update_reason_value': True,
                'delay_days': delay,
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert BlocklistSubmission.objects.count() == 1
        return (new_addon, existing_and_complete, partial_addon, existing_and_partial)

    def _test_add_multiple_verify_blocks(
        self,
        new_addon,
        existing_and_full,
        partial_addon,
        existing_and_partial,
        has_signoff=True,
    ):
        assert Block.objects.count() == 3
        assert BlocklistSubmission.objects.count() == 1
        submission = BlocklistSubmission.objects.get()
        all_blocks = Block.objects.all()
        partial_addon_decision, new_addon_decision = list(ContentDecision.objects.all())

        new_block = all_blocks[2]
        assert new_addon_decision.addon == new_addon
        assert new_block.addon == new_addon
        assert new_block.average_daily_users_snapshot == new_block.current_adu
        logs = list(
            ActivityLog.objects.for_addons(new_addon)
            .exclude(action=amo.LOG.BLOCKLIST_SIGNOFF.id)
            .order_by('pk')
        )
        add_log = logs[0]
        change_status_log = logs[1]
        reject_log = logs[2]
        assert add_log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert add_log.arguments == [new_addon, new_addon.guid, new_block]
        assert add_log.details['blocked_versions'] == [
            new_addon.current_version.version
        ]
        assert add_log.details['added_versions'] == [new_addon.current_version.version]
        assert add_log.details['reason'] == 'some reason'
        if has_signoff:
            assert add_log.details['signoff_state'] == 'Approved'
            assert add_log.details['signoff_by'] == submission.signoff_by.id
        else:
            assert add_log.details['signoff_state'] == 'Auto Sign-off'
            assert 'signoff_by' not in add_log.details
        block_log = (
            ActivityLog.objects.for_block(new_block)
            .filter(action=add_log.action)
            .last()
        )
        assert block_log == add_log
        version_reject_log, version_block_log = tuple(
            ActivityLog.objects.for_versions(new_addon.current_version)
        )
        if version_reject_log != reject_log:
            version_reject_log, version_block_log = (
                version_block_log,
                version_reject_log,
            )
        assert version_reject_log == reject_log
        assert version_block_log.action == amo.LOG.BLOCKLIST_VERSION_BLOCKED.id
        assert version_block_log.arguments == [new_addon.current_version, new_block]

        assert reject_log.action == amo.LOG.REJECT_VERSION.id
        assert reject_log.arguments == [
            new_addon,
            new_addon.current_version,
            new_addon_decision,
        ]
        assert reject_log.user == new_block.updated_by
        assert (
            reject_log
            == ActivityLog.objects.for_versions(new_addon.current_version).order_by(
                'pk'
            )[1]
        )
        assert change_status_log.action == amo.LOG.CHANGE_STATUS.id

        existing_and_partial = existing_and_partial.reload()
        assert all_blocks[1] == existing_and_partial
        assert partial_addon_decision.addon == partial_addon
        # confirm properties were updated
        assert all(ver.is_blocked for ver in partial_addon.versions.all())
        assert existing_and_partial.reason == 'some reason'
        assert existing_and_partial.url == 'dfd'
        assert existing_and_partial.average_daily_users_snapshot == (
            existing_and_partial.current_adu
        )
        logs = list(
            ActivityLog.objects.for_addons(partial_addon)
            .exclude(action=amo.LOG.BLOCKLIST_SIGNOFF.id)
            .order_by('pk')
        )
        edit_log = logs[0]
        reject_log = logs[1]
        assert edit_log.action == amo.LOG.BLOCKLIST_BLOCK_EDITED.id
        assert edit_log.arguments == [
            partial_addon,
            partial_addon.guid,
            existing_and_partial,
        ]
        assert edit_log.details['blocked_versions'] == [
            version
            for version in sorted(
                partial_addon.versions.all().values_list('version', flat=True)
            )
        ]
        assert edit_log.details['added_versions'] == [
            partial_addon.current_version.version
        ]
        assert edit_log.details['reason'] == 'some reason'
        if has_signoff:
            assert edit_log.details['signoff_state'] == 'Approved'
            assert edit_log.details['signoff_by'] == submission.signoff_by.id
        else:
            assert edit_log.details['signoff_state'] == 'Auto Sign-off'
            assert 'signoff_by' not in edit_log.details
        block_log = (
            ActivityLog.objects.for_block(existing_and_partial)
            .filter(action=edit_log.action)
            .first()
        )
        assert block_log == edit_log
        version_reject_log, version_block_log = tuple(
            ActivityLog.objects.for_versions(partial_addon.current_version)
        )
        if version_reject_log != reject_log:
            version_reject_log, version_block_log = (
                version_block_log,
                version_reject_log,
            )
        assert version_reject_log == reject_log
        assert version_block_log.action == amo.LOG.BLOCKLIST_VERSION_BLOCKED.id
        assert version_block_log.arguments == [
            partial_addon.current_version,
            existing_and_partial,
        ]

        assert reject_log.action == amo.LOG.REJECT_VERSION.id
        assert reject_log.arguments == [
            partial_addon,
            partial_addon.current_version,
            partial_addon_decision,
        ]
        assert reject_log.user == new_block.updated_by
        assert change_status_log.action == amo.LOG.CHANGE_STATUS.id

        existing_and_full = existing_and_full.reload()
        assert all_blocks[0] == existing_and_full
        # confirm properties *were not* updated.
        assert existing_and_full.reason != 'some reason'
        assert existing_and_full.url != 'dfd'
        assert not existing_and_full.average_daily_users_snapshot == (
            existing_and_full.current_adu
        )
        assert not ActivityLog.objects.for_addons(existing_and_full.addon).exists()
        assert not ActivityLog.objects.for_versions(
            existing_and_full.addon.current_version
        ).exists()

        assert submission.input_guids == (
            'any@new\npartial@existing\nfull@existing\ninvalid@'
        )
        assert submission.url == new_block.url
        assert submission.reason == new_block.reason

        assert submission.to_block == [
            {
                'guid': 'any@new',
                'id': None,
                'average_daily_users': new_addon.average_daily_users,
            },
            {
                'guid': 'partial@existing',
                'id': existing_and_partial.id,
                'average_daily_users': partial_addon.average_daily_users,
            },
        ]
        assert set(submission.block_set.all()) == {new_block, existing_and_partial}

        new_addon_version = new_addon.current_version
        new_addon.reload()
        new_addon_version.file.reload()
        assert new_addon.status == amo.STATUS_DISABLED
        assert new_addon_version.file.status == amo.STATUS_DISABLED
        partial_addon_version = partial_addon.current_version
        partial_addon.reload()
        partial_addon_version.file.reload()
        assert partial_addon.status == amo.STATUS_DISABLED
        assert partial_addon_version.file.status == (amo.STATUS_DISABLED)

    def test_soften(self):
        addon = addon_factory(guid='guid@')
        version = addon.current_version
        block = block_factory(
            guid=addon.guid,
            updated_by=user_factory(),
        )
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        response = self.client.get(
            self.submission_url,
            {
                'guids': str(addon.guid),
                'action': str(BlocklistSubmission.ACTIONS.SOFTEN),
            },
        )
        doc = pq(response.content)
        assert doc('#id_block_type').attr('value') == str(BlockType.SOFT_BLOCKED)

        response = self.client.post(
            self.submission_url,
            {
                'input_guids': str(addon.guid),
                'action': str(BlocklistSubmission.ACTIONS.SOFTEN),
                'block_type': str(BlockType.SOFT_BLOCKED),
                'changed_version_ids': [
                    version.id,
                ],
                'disable_addon': False,
                'url': 'dfd',
                'reason': 'some reason',
                'update_url_value': True,
                'update_reason_value': True,
                'delay_days': 0,
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert version.blockversion.reload().block_type == BlockType.SOFT_BLOCKED
        assert block.reload().updated_by == user

    def test_harden(self):
        addon = addon_factory(guid='guid@')
        version = addon.current_version
        block = block_factory(
            guid=addon.guid,
            updated_by=user_factory(),
            block_type=BlockType.SOFT_BLOCKED,
        )
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        response = self.client.get(
            self.submission_url,
            {
                'guids': str(addon.guid),
                'action': str(BlocklistSubmission.ACTIONS.HARDEN),
            },
        )
        doc = pq(response.content)
        assert doc('#id_block_type').attr('value') == str(BlockType.BLOCKED)

        response = self.client.post(
            self.submission_url,
            {
                'input_guids': str(addon.guid),
                'action': str(BlocklistSubmission.ACTIONS.HARDEN),
                'block_type': str(BlockType.BLOCKED),
                'changed_version_ids': [
                    version.id,
                ],
                'disable_addon': False,
                'url': 'dfd',
                'reason': 'some reason',
                'update_url_value': True,
                'update_reason_value': True,
                'delay_days': 0,
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert version.blockversion.reload().block_type == BlockType.BLOCKED
        assert block.reload().updated_by == user

    def test_submit_no_dual_signoff(self):
        addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        (
            new_addon,
            existing_and_full,
            partial_addon,
            existing_and_partial,
        ) = self._test_add_multiple_submit(addon_adu=addon_adu)
        self._test_add_multiple_verify_blocks(
            new_addon,
            existing_and_full,
            partial_addon,
            existing_and_partial,
            has_signoff=False,
        )

    def test_submit_dual_signoff(self):
        addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD + 1
        (
            new_addon,
            existing_and_full,
            partial_addon,
            existing_and_partial,
        ) = self._test_add_multiple_submit(addon_adu=addon_adu)
        # no new Block objects yet
        assert Block.objects.count() == 2
        # and existing block wasn't updated

        multi = BlocklistSubmission.objects.get()
        assert multi.block_type == BlockType.BLOCKED
        multi.update(
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.APPROVED,
            signoff_by=user_factory(),
        )
        assert multi.is_submission_ready
        multi.save_to_block_objects()
        self._test_add_multiple_verify_blocks(
            new_addon, existing_and_full, partial_addon, existing_and_partial
        )

    def test_submit_no_metadata_updates(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        new_addon = addon_factory(
            guid='any@new', name='New Danger', average_daily_users=addon_adu
        )
        partial_addon_adu = addon_adu - 1
        partial_addon = addon_factory(
            guid='partial@existing',
            name='Partial Danger',
            average_daily_users=(partial_addon_adu),
        )
        existing_and_partial = block_factory(
            guid=partial_addon.guid,
            # should be updated to addon's adu
            average_daily_users_snapshot=146722437,
            updated_by=user_factory(),
            reason='partial reason',
            url='partial url',
        )
        version_factory(addon=partial_addon)
        existing_and_complete = block_factory(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            # addon will have a different adu
            average_daily_users_snapshot=346733434,
            updated_by=user_factory(),
            reason='full reason',
            url='full url',
        )

        # Create the block submission
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': ('any@new\npartial@existing\nfull@existing\ninvalid@'),
                'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
                'block_type': BlockType.BLOCKED,
                'changed_version_ids': [
                    new_addon.current_version.id,
                    partial_addon.current_version.id,
                ],
                'disable_addon': True,
                'url': 'new url that will be ignored because no update_url_value=True',
                'reason': 'new reason',
                # no 'update_url_value'
                'update_reason_value': True,
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert BlocklistSubmission.objects.count() == 1
        submission = BlocklistSubmission.objects.get()
        assert submission.reason == 'new reason'
        assert submission.url is None
        assert Block.objects.count() == 3
        new_block = Block.objects.exclude(
            id__in=[existing_and_complete.id, existing_and_partial.id]
        ).get()

        existing_and_complete.reload()
        existing_and_partial.reload()

        assert existing_and_complete.reason == 'full reason'  # not affected at all
        assert existing_and_partial.reason == 'new reason'
        assert new_block.reason == 'new reason'
        assert existing_and_complete.url == 'full url'  # not affected at all
        assert existing_and_partial.url == 'partial url'  # .url is None
        assert new_block.url == ''

    @mock.patch('olympia.blocklist.forms.GUID_FULL_LOAD_LIMIT', 1)
    def test_add_multiple_bulk_so_fake_block_objects(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        new_addon = addon_factory(guid='any@new', name='New Danger')
        block_factory(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            updated_by=user_factory(),
        )
        partial_addon = addon_factory(guid='partial@existing', name='Partial Danger')
        block_factory(
            addon=partial_addon,
            updated_by=user_factory(),
            version_ids=[],
        )
        block_factory(
            addon=addon_factory(guid='regex@legacy'),
            updated_by=user_factory(),
        )
        response = self.client.post(
            self.submission_url,
            {
                'guids': 'any@new\npartial@existing\nfull@existing\ninvalid@\n'
                'regex@legacy',
                'changed_version_ids': [
                    new_addon.current_version.id,
                    partial_addon.current_version.id,
                ],
            },
            follow=True,
        )
        content = response.content.decode('utf-8')
        # This metadata should exist
        assert new_addon.guid in content
        assert f'{new_addon.average_daily_users} users' in content
        assert partial_addon.guid in content
        assert f'{partial_addon.average_daily_users} users' in content
        assert 'full@existing' in content
        assert 'invalid@' in content
        assert 'regex@legacy' in content

        # But Addon names or review links shouldn't have been loaded
        assert 'New Danger' not in content
        assert 'Partial Danger' not in content
        assert 'Full Danger' not in content
        assert 'Review Listed' not in content
        assert 'Review Unlisted' not in content

    def test_review_links(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)
        post_kwargs = {
            'path': self.submission_url,
            'data': {'guids': 'guid@\nfoo@baa\ninvalid@'},
            'follow': True,
        }

        # An addon with only listed versions should have listed link
        addon = addon_factory(
            guid='guid@', name='Danger Danger', version_kw={'version': '0.1'}
        )
        # This is irrelevant because a completed block doesn't have links
        block_factory(
            addon=addon_factory(guid='foo@baa'),
            updated_by=user_factory(),
        )
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' not in response.content
        assert b'Edit Block' not in response.content
        assert not pq(response.content)('.existing_block')

        # Should work the same if partial block (exists but needs updating)
        existing_block = block_factory(
            version_ids=[], guid=addon.guid, updated_by=user_factory()
        )
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' not in response.content
        assert pq(response.content)('.existing_block a').attr('href') == (
            reverse('admin:blocklist_block_change', args=(existing_block.pk,))
        )
        assert pq(response.content)('.existing_block').text() == ('[Edit Block]')

        # And an unlisted version
        version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED, version='0.2')
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' in response.content
        assert pq(response.content)('.existing_block a').attr('href') == (
            reverse('admin:blocklist_block_change', args=(existing_block.pk,))
        )
        assert pq(response.content)('.existing_block').text() == ('[Edit Block]')

        # And delete the block again
        existing_block.delete()
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' in response.content
        assert b'Edit Block' not in response.content
        assert not pq(response.content)('.existing_block')

        addon.current_version.delete(hard=True)
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' not in response.content
        assert b'Review Unlisted' in response.content

    def test_can_not_add_without_create_permission(self):
        user = user_factory(email='someone@mozilla.com')
        # The signoff permission shouldn't be sufficient
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.force_login(user)

        addon_factory(guid='guid@', name='Danger Danger')
        existing = block_factory(
            addon=addon_factory(guid='foo@baa'),
            updated_by=user_factory(),
        )
        response = self.client.post(
            self.submission_url, {'guids': 'guid@\nfoo@baa\ninvalid@'}, follow=True
        )
        assert response.status_code == 403
        assert b'Danger Danger' not in response.content

        # Try to create the block anyway
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': 'guid@\nfoo@baa\ninvalid@',
                'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
                'block_type': BlockType.BLOCKED,
                'url': 'dfd',
                'reason': 'some reason',
                'update_url_value': True,
                'update_reason_value': True,
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 403
        assert Block.objects.count() == 1
        existing = existing.reload()
        assert existing.reason == ''  # check the values didn't update.

    def _test_can_list_with_permission(self, permission):
        # add some guids to the multi block to test out the counts in the list
        addon = addon_factory(guid='guid@', name='Danger Danger')
        block = block_factory(
            version_ids=[],
            addon=addon_factory(
                guid='block@', name='High Voltage', average_daily_users=1
            ),
            updated_by=user_factory(),
        )
        add_change_subm = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@\nblock@',
            updated_by=user_factory(display_name='Bób'),
            action=BlocklistSubmission.ACTIONS.ADDCHANGE,
        )
        delete_subm = BlocklistSubmission.objects.create(
            input_guids='block@',
            updated_by=user_factory(display_name='Sué'),
            action=BlocklistSubmission.ACTIONS.DELETE,
        )
        add_change_subm.save()
        delete_subm.save()
        assert add_change_subm.to_block == [
            {
                'guid': 'guid@',
                'id': None,
                'average_daily_users': addon.average_daily_users,
            },
            {
                'guid': 'block@',
                'id': block.id,
                'average_daily_users': block.addon.average_daily_users,
            },
        ]
        assert delete_subm.to_block == [
            {
                'guid': 'block@',
                'id': block.id,
                'average_daily_users': block.addon.average_daily_users,
            },
        ]

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, permission)
        self.client.force_login(user)

        response = self.client.get(self.submission_list_url, follow=True)
        assert response.status_code == 200
        assert 'Bób' in response.content.decode('utf-8')
        assert 'Sué' in response.content.decode('utf-8')
        doc = pq(response.content)
        assert doc('th.field-blocks_count').text() == '1 add-ons 2 add-ons'
        assert doc('.field-action').text() == ('Delete Block Add/Change Block')
        assert doc('.field-state').text() == 'Pending Sign-off Pending Sign-off'

    def test_can_list_with_blocklist_create(self):
        self._test_can_list_with_permission('Blocklist:Create')

    def test_can_list_with_blocklist_signoff(self):
        self._test_can_list_with_permission('Blocklist:Signoff')

    def test_can_not_list_without_permission(self):
        BlocklistSubmission.objects.create(updated_by=user_factory(display_name='Bób'))
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)

        response = self.client.get(self.submission_list_url, follow=True)
        assert response.status_code == 403
        assert 'Bób' not in response.content.decode('utf-8')

    def test_edit_with_blocklist_create(self):
        threshold = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        addon = addon_factory(
            guid='guid@', name='Danger Danger', average_daily_users=threshold + 1
        )
        first_version = addon.current_version
        second_version = version_factory(addon=addon)
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@\nsecond@invalid',
            updated_by=user_factory(),
            changed_version_ids=[first_version.id, second_version.id],
        )
        assert mbs.to_block == [
            {
                'guid': 'guid@',
                'id': None,
                'average_daily_users': addon.average_daily_users,
            }
        ]

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )

        response = self.client.get(multi_url, follow=True)
        assert response.status_code == 200
        assert b'guid@<br>invalid@<br>second@invalid' in response.content
        doc = pq(response.content.decode('utf-8'))
        # Can't change block type when approving
        assert not doc('.field_block_type select')
        assert doc('.field-block_type .readonly').text() == '🛑 Hard-Blocked'
        buttons = doc('.submit-row input')
        assert buttons[0].attrib['value'] == 'Update'
        assert len(buttons) == 1
        assert b'Reject Submission' not in response.content
        assert b'Approve Submission' not in response.content

        response = self.client.post(
            multi_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'changed_version_ids': [first_version.id],
                'url': 'new.url',
                # disable_addon defaults to True, so omitting it is changing to False
                'reason': 'a new reason thats longer than 40 charactors',
                'update_url_value': True,
                'update_reason_value': True,
                '_save': 'Update',
            },
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()

        # the read-only values above weren't changed.
        assert mbs.input_guids == 'guid@\ninvalid@\nsecond@invalid'
        assert mbs.changed_version_ids == [first_version.id]
        # but the other details were
        assert mbs.url == 'new.url'
        assert mbs.reason == 'a new reason thats longer than 40 charactors'
        assert mbs.disable_addon is False

        # The blocklistsubmission wasn't approved or rejected though
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PENDING
        assert Block.objects.count() == 0

        log_entry = LogEntry.objects.get()
        assert log_entry.user == user
        assert log_entry.object_id == str(mbs.id)
        change_json = json.loads(log_entry.change_message)
        # change_message fields are the Field names rather than the fields in django3.2
        change_json[0]['changed']['fields'] = [
            field.lower() for field in change_json[0]['changed']['fields']
        ]
        assert change_json == [
            {
                'changed': {
                    'fields': [
                        'changed_version_ids',
                        'disable addon',
                        'update_url_value',
                        'url',
                        'update_reason_value',
                        'reason',
                    ]
                }
            }
        ]

        response = self.client.get(multi_url, follow=True)
        assert (
            f'Changed {FANCY_QUOTE_OPEN}Pending Sign-off: guid@, invalid@, '
            'second@invalid; new.url; a new reason thats longer than 40 cha...'
            in response.content.decode('utf-8')
        )

    def test_edit_page_with_blocklist_signoff(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@\nsecond@invalid',
            updated_by=user_factory(),
            changed_version_ids=[addon.current_version.id],
        )
        assert mbs.to_block == [
            {
                'guid': 'guid@',
                'id': None,
                'average_daily_users': addon.average_daily_users,
            }
        ]

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.force_login(user)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )

        response = self.client.get(multi_url, follow=True)
        assert response.status_code == 200
        assert b'guid@<br>invalid@<br>second@invalid' in response.content
        doc = pq(response.content)
        buttons = doc('.submit-row input')
        assert len(buttons) == 2
        assert buttons[0].attrib['value'] == 'Reject Submission'
        assert buttons[1].attrib['value'] == 'Approve Submission'

        # Try to submit an update - no signoff approve or reject
        response = self.client.post(
            multi_url,
            {
                'input_guids': 'guid2@\nfoo@baa',
                'action': str(BlocklistSubmission.ACTIONS.DELETE),
                'changed_version_ids': [],
                'url': 'new.url',
                'reason': 'a reason',
                'update_url_value': True,
                'update_reason_value': True,
                '_save': 'Update',
            },
            follow=True,
        )
        assert response.status_code == 403
        mbs = mbs.reload()

        # none of the values above were changed because they're all read-only.
        assert mbs.input_guids == 'guid@\ninvalid@\nsecond@invalid'
        assert mbs.action == 0
        assert mbs.changed_version_ids != []
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

        # The blocklistsubmission wasn't approved or rejected either
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PENDING
        assert Block.objects.count() == 0
        assert LogEntry.objects.count() == 0

    def test_signoff_approve(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        version = addon.current_version
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@',
            updated_by=user_factory(),
            changed_version_ids=[version.id],
        )
        assert mbs.to_block == [
            {
                'guid': 'guid@',
                'id': None,
                'average_daily_users': addon.average_daily_users,
            }
        ]

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.force_login(user)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )
        response = self.client.post(
            multi_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'changed_version_ids': [],  # should be ignored
                'url': 'new.url',  # should be ignored
                'reason': 'a reason',  # should be ignored
                'update_url_value': True,
                'update_reason_value': True,
                '_approve': 'Approve Submission',
            },
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()
        assert mbs.signoff_by == user

        # the read-only values above weren't changed.
        assert mbs.input_guids == 'guid@\ninvalid@'
        assert mbs.changed_version_ids != []
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

        # As it was signed off, the block should have been created
        assert Block.objects.count() == 1
        new_block = Block.objects.get()

        assert new_block.addon == addon
        decision = ContentDecision.objects.get()
        assert decision.addon == addon
        logs = ActivityLog.objects.for_addons(addon)
        change_status_log = logs[0]
        reject_log = logs[1]
        signoff_log = logs[2]
        add_log = logs[3]
        assert add_log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert add_log.arguments == [addon, addon.guid, new_block]
        assert add_log.details['blocked_versions'] == [addon.current_version.version]
        assert add_log.details['added_versions'] == [addon.current_version.version]
        assert add_log.details['reason'] == ''
        assert add_log.details['signoff_state'] == 'Approved'
        assert add_log.details['signoff_by'] == user.id
        assert add_log.user == mbs.updated_by
        block_log = (
            ActivityLog.objects.for_block(new_block)
            .filter(action=add_log.action)
            .last()
        )
        assert block_log == add_log
        version_reject_log, version_block_log = tuple(
            ActivityLog.objects.for_versions(addon.current_version)
        )
        assert version_reject_log == reject_log
        assert version_block_log.action == amo.LOG.BLOCKLIST_VERSION_BLOCKED.id
        assert version_block_log.arguments == [addon.current_version, new_block]

        assert signoff_log.action == amo.LOG.BLOCKLIST_SIGNOFF.id
        assert signoff_log.arguments == [addon, addon.guid, 'add', new_block]
        assert signoff_log.user == user

        assert reject_log.action == amo.LOG.REJECT_VERSION.id
        assert reject_log.arguments == [addon, version, decision]
        assert reject_log.user == new_block.updated_by
        assert (
            reject_log
            == ActivityLog.objects.for_versions(addon.current_version).first()
        )

        assert change_status_log.action == amo.LOG.CHANGE_STATUS.id

        assert mbs.to_block == [
            {
                'guid': 'guid@',
                'id': None,
                'average_daily_users': addon.average_daily_users,
            }
        ]
        assert list(mbs.block_set.all()) == [new_block]

        log_entry = LogEntry.objects.last()
        assert log_entry.user == user
        assert log_entry.object_id == str(mbs.id)
        other_obj = collection_factory(id=mbs.id, name='not a Block!')
        LogEntry.objects.log_action(
            user_factory().id,
            ContentType.objects.get_for_model(other_obj).pk,
            other_obj.id,
            repr(other_obj),
            ADDITION,
            str(other_obj),
        )

        response = self.client.get(multi_url, follow=True)
        assert (
            f'Changed {FANCY_QUOTE_OPEN}Approved: guid@, invalid@'
            f'{FANCY_QUOTE_CLOSE} {LONG_DASH} Sign-off Approval'
            in response.content.decode('utf-8')
        )
        assert b'not a Block!' not in response.content

        # we disabled versions and the addon (because 0 - *)
        addon.reload()
        version.file.reload()
        assert addon.status == amo.STATUS_DISABLED
        assert version.file.status == amo.STATUS_DISABLED

    def test_signoff_reject(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        version = addon.current_version
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@',
            updated_by=user_factory(),
            changed_version_ids=[version.id],
        )
        assert mbs.to_block == [
            {
                'guid': 'guid@',
                'id': None,
                'average_daily_users': addon.average_daily_users,
            }
        ]

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.force_login(user)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )
        response = self.client.post(
            multi_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'changed_version_ids': [],  # should be ignored
                'url': 'new.url',  # should be ignored
                'reason': 'a reason',  # should be ignored
                'update_url_value': True,
                'update_reason_value': True,
                '_reject': 'Reject Submission',
            },
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()

        # the read-only values above weren't changed.
        assert mbs.input_guids == 'guid@\ninvalid@'
        assert mbs.changed_version_ids != []
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

        # And the blocklistsubmission was rejected, so no Blocks created
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.REJECTED
        assert Block.objects.count() == 0
        assert not mbs.is_submission_ready

        log_entry = LogEntry.objects.last()
        assert log_entry.user == user
        assert log_entry.object_id == str(mbs.id)
        other_obj = collection_factory(id=mbs.id, name='not a Block!')
        LogEntry.objects.log_action(
            user_factory().id,
            ContentType.objects.get_for_model(other_obj).pk,
            other_obj.id,
            repr(other_obj),
            ADDITION,
            str(other_obj),
        )

        response = self.client.get(multi_url, follow=True)
        content = response.content.decode('utf-8')
        assert (
            f'Changed {FANCY_QUOTE_OPEN}Rejected: guid@, invalid@'
            f'{FANCY_QUOTE_CLOSE} {LONG_DASH} Sign-off Rejection' in content
        )
        assert 'not a Block!' not in content

        # statuses didn't change
        addon.reload()
        version.reload()
        assert addon.status != amo.STATUS_DISABLED
        assert version.file.status != amo.STATUS_DISABLED

    def test_cannot_approve_with_only_block_create_permission(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@',
            updated_by=user_factory(),
            changed_version_ids=[addon.current_version.id],
        )
        assert mbs.to_block == [
            {
                'guid': 'guid@',
                'id': None,
                'average_daily_users': addon.average_daily_users,
            }
        ]

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )
        response = self.client.post(
            multi_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'changed_version_ids': [addon.current_version.id],
                'url': 'new.url',  # could be updated with this permission
                'reason': 'a reason',  # could be updated with this permission
                'update_url_value': True,
                'update_reason_value': True,
                '_approve': 'Approve Submission',
            },
            follow=True,
        )
        assert response.status_code == 403
        mbs = mbs.reload()
        # It wasn't signed off
        assert not mbs.signoff_by
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PENDING
        # And the details weren't updated either
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

    def test_can_only_reject_your_own_with_only_block_create_permission(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        submission = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@',
            updated_by=user_factory(),
            changed_version_ids=[addon.current_version.id],
        )
        assert submission.to_block == [
            {
                'guid': 'guid@',
                'id': None,
                'average_daily_users': addon.average_daily_users,
            }
        ]

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)
        change_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(submission.id,)
        )
        response = self.client.post(
            change_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'changed_version_ids': [addon.current_version.id],
                'url': 'new.url',  # could be updated with this permission
                'reason': 'a reason',  # could be updated with this permission
                'update_url_value': True,
                'update_reason_value': True,
                '_reject': 'Reject Submission',
            },
            follow=True,
        )
        assert response.status_code == 403
        submission = submission.reload()
        # It wasn't signed off
        assert not submission.signoff_by
        assert submission.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PENDING
        # And the details weren't updated either
        assert submission.url != 'new.url'
        assert submission.reason != 'a reason'

        # except if it's your own submission
        submission.update(updated_by=user)
        response = self.client.get(change_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        buttons = doc('.submit-row input')
        assert buttons[0].attrib['value'] == 'Update'
        assert buttons[1].attrib['value'] == 'Reject Submission'
        assert len(buttons) == 2
        assert b'Approve Submission' not in response.content

        response = self.client.post(
            change_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'changed_version_ids': [addon.current_version.id],
                'url': 'new.url',  # could be updated with this permission
                'reason': 'a reason',  # could be updated with this permission
                'update_url_value': True,
                'update_reason_value': True,
                '_reject': 'Reject Submission',
            },
            follow=True,
        )
        assert response.status_code == 200
        submission = submission.reload()
        assert submission.signoff_state == BlocklistSubmission.SIGNOFF_STATES.REJECTED
        assert not submission.signoff_by
        assert submission.url == 'new.url'
        assert submission.reason == 'a reason'

    def test_signed_off_view(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@\nsecond@invalid',
            updated_by=user_factory(),
            signoff_by=user_factory(),
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.APPROVED,
            changed_version_ids=[addon.current_version.id],
        )
        assert mbs.to_block == [
            {
                'guid': 'guid@',
                'id': None,
                'average_daily_users': addon.average_daily_users,
            }
        ]
        mbs.save_to_block_objects()
        block = Block.objects.get()
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PUBLISHED
        # update addon adu to something different
        assert block.average_daily_users_snapshot == addon.average_daily_users
        addon.update(average_daily_users=1234)

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)
        multi_view_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )

        response = self.client.get(multi_view_url, follow=True)
        assert response.status_code == 200
        assert b'guid@<br>invalid@<br>second@invalid' in response.content
        doc = pq(response.content)
        (review_link, guid_link) = doc('div.field-ro_changed_version_ids div div a')
        assert review_link.attrib['href'] == absolutify(
            reverse('reviewers.review', args=(addon.pk,))
        )
        assert guid_link.attrib['href'] == reverse(
            'admin:blocklist_block_change', args=(block.pk,)
        )
        assert not doc('submit-row input')
        assert str(block.average_daily_users_snapshot) in (
            response.content.decode('utf-8')
        )
        assert b'[Block Deleted]' not in response.content

        # Now check what the page looks like if the guid is subsequently unblocked
        block.delete()
        response = self.client.get(multi_view_url, follow=True)
        assert response.status_code == 200
        assert b'guid@<br>invalid@<br>second@invalid' in response.content
        doc = pq(response.content)
        (review_link,) = doc('div.field-ro_changed_version_ids div div a')
        assert review_link.attrib['href'] == absolutify(
            reverse('reviewers.review', args=(addon.pk,))
        )
        assert b'[Block Deleted]' in response.content

    def test_list_filters(self):
        now = datetime.now()
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.force_login(user)
        addon_factory(guid='pending1@')
        addon_factory(guid='pending2@')
        addon_factory(guid='published@')
        BlocklistSubmission.objects.create(
            input_guids='pending1@\npending2@',
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.PENDING,
        )
        BlocklistSubmission.objects.create(
            input_guids='missing@',
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.APPROVED,
            delayed_until=now + timedelta(days=1),
        )
        BlocklistSubmission.objects.create(
            input_guids='published@',
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.PUBLISHED,
            delayed_until=now - timedelta(days=1),
        )

        response = self.client.get(self.submission_list_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)

        # default is to only show Pending Sign-off (signoff_state=0)
        assert doc('#result_list tbody tr').length == 1
        assert doc('.field-blocks_count').text() == '2 add-ons'

        expected_filters = [
            ('All', '?signoff_state=all'),
            ('Delayed', '?signoff_state=delayed'),
            ('Pending Sign-off', '?signoff_state=0'),
            ('Approved', '?signoff_state=1'),
            ('Rejected', '?signoff_state=2'),
            ('Auto Sign-off', '?signoff_state=3'),
            ('Published', '?signoff_state=4'),
        ]
        filters = [(x.text, x.attrib['href']) for x in doc('#changelist-filter a')]
        assert filters == expected_filters
        # Should be shown as selected too
        assert doc('#changelist-filter li.selected a').text() == 'Pending Sign-off'

        # Repeat with the Pending filter explictly selected
        response = self.client.get(self.submission_list_url, {'signoff_state': 0})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        assert doc('.field-blocks_count').text() == '2 add-ons'
        assert doc('#changelist-filter li.selected a').text() == 'Pending Sign-off'
        assert doc('#changelist-form td.field-state').text() == 'Pending Sign-off'

        # The delayed filter should show a different selection of submissions
        response = self.client.get(
            self.submission_list_url, {'signoff_state': 'delayed'}
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        assert doc('.field-blocks_count').text() == '0 add-ons'
        assert doc('#changelist-filter li.selected a').text() == 'Delayed'
        assert doc('#changelist-form td.field-state').text() == 'Approved:Delayed'

        # And then lastly with all submissions showing
        response = self.client.get(self.submission_list_url, {'signoff_state': 'all'})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 3
        assert doc('#changelist-filter li.selected a').text() == 'All'
        assert doc('#changelist-form td.field-state').text() == (
            'Published Approved:Delayed Pending Sign-off'
        )

    def test_blocked_deleted_keeps_addon_status(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        deleted_addon = addon_factory(guid='guid@', version_kw={'version': '1.2.5'})
        version = deleted_addon.current_version
        NeedsHumanReview.objects.create(version=version)
        deleted_addon.update(status=amo.STATUS_DELETED)
        version.update(deleted=True)
        version.file.update(status=amo.STATUS_DISABLED)
        assert not DeniedGuid.objects.filter(guid=deleted_addon.guid).exists()

        response = self.client.get(self.submission_url + '?guids=guid@', follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert deleted_addon.guid in content
        assert Block.objects.count() == 0  # Check we didn't create it already
        assert 'Block History' in content

        # Create the block
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': 'guid@',
                'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
                'block_type': BlockType.BLOCKED,
                'changed_version_ids': [version.id],
                'disable_addon': True,
                'url': 'dfd',
                'reason': 'some reason',
                'update_url_value': True,
                'update_reason_value': True,
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert Block.objects.count() == 1
        block = Block.objects.first()
        assert block.addon == deleted_addon
        deleted_addon.reload()
        assert deleted_addon.status == amo.STATUS_DELETED  # Should stay deleted
        assert DeniedGuid.objects.filter(guid=deleted_addon.guid).exists()
        version.reload()
        version.file.reload()
        assert version.file.status == amo.STATUS_DISABLED
        assert not version.needshumanreview_set.filter(is_active=True).exists()

    def test_blocking_addon_guid_already_denied(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        deleted_addon = addon_factory(guid='guid@', version_kw={'version': '1.2.5'})
        version = deleted_addon.current_version
        deleted_addon.update(status=amo.STATUS_DELETED)
        version.update(deleted=True)
        deleted_addon.deny_resubmission()
        assert DeniedGuid.objects.filter(guid=deleted_addon.guid).exists()

        response = self.client.get(self.submission_url + '?guids=guid@', follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert deleted_addon.guid in content
        assert Block.objects.count() == 0  # Check we didn't create it already
        assert 'Block History' in content

        # Create the block
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': 'guid@',
                'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
                'block_type': BlockType.BLOCKED,
                'changed_version_ids': [version.id],
                'url': 'dfd',
                'reason': 'some reason',
                'update_url_value': True,
                'update_reason_value': True,
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert Block.objects.count() == 1
        block = Block.objects.first()
        assert block.addon == deleted_addon
        deleted_addon.reload()
        assert deleted_addon.status == amo.STATUS_DELETED  # Should stay deleted
        assert DeniedGuid.objects.filter(guid=deleted_addon.guid).exists()

    def test_add_with_delayed(self):
        delay_days = 2
        addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD - 1
        with time_machine.travel('2023-01-01 12:34:56', tick=False) as frozen_time:
            (
                new_addon,
                existing_and_full,
                partial_addon,
                existing_and_partial,
            ) = self._test_add_multiple_submit(addon_adu=addon_adu, delay=delay_days)
            # no new Block objects yet even though under the threshold
            assert Block.objects.count() == 2
            multi = BlocklistSubmission.objects.get()
            assert (
                multi.signoff_state == BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED
            )
            assert not multi.is_submission_ready

            frozen_time.shift(delta=timedelta(days=delay_days, seconds=1))
            # Now we're past, the submission is ready
            assert multi.is_submission_ready
            assert (
                multi.signoff_state == BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED
            )

            multi.save_to_block_objects()
            self._test_add_multiple_verify_blocks(
                new_addon,
                existing_and_full,
                partial_addon,
                existing_and_partial,
                has_signoff=False,
            )
            assert (
                multi.reload().signoff_state
                == BlocklistSubmission.SIGNOFF_STATES.PUBLISHED
            )

    def test_approve_delayed(self):
        now = datetime.now()
        addon = addon_factory(
            guid='guid@',
            average_daily_users=settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD - 1,
        )
        mbs = BlocklistSubmission.objects.create(
            input_guids=addon.guid,
            updated_by=user_factory(),
            delayed_until=now + timedelta(days=2),
        )
        assert mbs.to_block[0]['guid'] == addon.guid
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PENDING

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.force_login(user)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )
        response = self.client.post(
            multi_url,
            {
                '_approve': 'Approve Submission',
            },
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()
        assert mbs.signoff_by == user

        # Approved but not published
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.APPROVED
        # And no blocks have been created
        assert not Block.objects.exists()

        response = self.client.get(multi_url, follow=True)
        assert (
            f'Changed {FANCY_QUOTE_OPEN}Approved: {addon.guid}{FANCY_QUOTE_CLOSE} '
            f'{LONG_DASH} Sign-off Approval' in response.content.decode('utf-8')
        )

    def test_reject_delayed(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        version = addon.current_version
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@',
            changed_version_ids=[version.id],
            updated_by=user_factory(),
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED,
            delayed_until=datetime.now() + timedelta(days=1),
        )
        assert mbs.to_block[0]['guid'] == 'guid@'

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.force_login(user)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )
        response = self.client.post(
            multi_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'changed_version_ids': [],  # should be ignored
                'url': 'new.url',  # should be ignored
                'reason': 'a reason',  # should be ignored
                'update_url_value': True,
                'update_reason_value': True,
                '_reject': 'Reject Submission',
            },
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()

        # the read-only values above weren't changed.
        assert mbs.input_guids == 'guid@\ninvalid@'
        assert mbs.changed_version_ids != []
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

        # And the blocklistsubmission was rejected, so no Blocks created
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.REJECTED
        assert Block.objects.count() == 0
        assert not mbs.is_submission_ready

        response = self.client.get(multi_url, follow=True)
        content = response.content.decode('utf-8')
        assert (
            f'Changed {FANCY_QUOTE_OPEN}Rejected: guid@, invalid@'
            f'{FANCY_QUOTE_CLOSE} {LONG_DASH} Sign-off Rejection' in content
        )

        # statuses didn't change
        addon.reload()
        version.reload()
        assert addon.status != amo.STATUS_DISABLED
        assert version.file.status != amo.STATUS_DISABLED

    def test_edit_delay(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        threshold = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        addon = addon_factory(guid='guid@', average_daily_users=threshold + 1)
        now = datetime.now()
        mbs = BlocklistSubmission.objects.create(
            input_guids=addon.guid,
            changed_version_ids=[addon.current_version.id],
            updated_by=user_factory(),
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.PENDING,
            delayed_until=now + timedelta(days=1),
        )
        assert mbs.to_block[0]['guid'] == addon.guid
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )

        # First a change to a date in the future
        data = {
            'delayed_until': now + timedelta(days=5),
            '_save': 'Update',
            'changed_version_ids': [addon.current_version.id],
        }
        response = self.client.post(
            multi_url,
            data,
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()
        # new delayed date
        assert mbs.delayed_until == now + timedelta(days=5), response.context[
            'adminform'
        ].form.errors
        # The blocklistsubmission wasn't approved or rejected though
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PENDING
        assert Block.objects.count() == 0

        # Then to a date that is already past
        data['delayed_until'] = now
        response = self.client.post(
            multi_url,
            data,
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()
        # new delayed date
        assert mbs.delayed_until == now
        # No change in state because it still needs signoff
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PENDING
        assert Block.objects.count() == 0

        # But if the submission didn't need dual signoff then it will be auto approved
        # reset the submission state first
        mbs.signoff_state = BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED
        mbs.delayed_until = now + timedelta(days=5)
        mbs.to_block[0]['average_daily_users'] = threshold - 1
        mbs.save()
        assert mbs.all_adu_safe()
        response = self.client.post(
            multi_url,
            data,
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()
        # new delayed date
        assert mbs.delayed_until == now
        # The submission is auto approved
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PUBLISHED
        assert Block.objects.count() == 1

    def test_not_disable_addon(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        new_addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD - 1
        new_addon = addon_factory(
            guid='any@new', name='New Danger', average_daily_users=new_addon_adu
        )
        partial_addon_adu = new_addon_adu - 1
        partial_addon = addon_factory(
            guid='partial@existing',
            name='Partial Danger',
            average_daily_users=(partial_addon_adu),
        )
        already_blocked_version = partial_addon.current_version
        block_factory(
            guid=partial_addon.guid,
            # should be updated to addon's adu
            average_daily_users_snapshot=146722437,
            updated_by=user_factory(),
        )
        version_factory(addon=partial_addon)
        assert Block.objects.count() == 1
        # Create the block submission
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': ('any@new\npartial@existing\nfull@existing\ninvalid@'),
                'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
                'block_type': BlockType.BLOCKED,
                'changed_version_ids': [
                    new_addon.current_version.id,
                    partial_addon.current_version.id,
                ],
                # 'disable_addon' it's a checkbox so leaving it out is False
                'url': 'dfd',
                'reason': 'some reason',
                'update_url_value': True,
                'update_reason_field': True,
                'delay_days': 0,
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200

        assert Block.objects.count() == 2
        assert BlocklistSubmission.objects.count() == 1

        new_addon_version = new_addon.current_version
        new_addon.reload()
        new_addon_version.file.reload()
        assert new_addon.status != amo.STATUS_DISABLED
        assert new_addon_version.file.status == amo.STATUS_DISABLED
        partial_addon_version = partial_addon.current_version
        partial_addon.reload()
        partial_addon_version.file.reload()
        assert partial_addon.status != amo.STATUS_DISABLED
        assert partial_addon_version.file.status == (amo.STATUS_DISABLED)

        assert not new_addon_version.blockversion.block_type == BlockType.SOFT_BLOCKED
        assert (
            not partial_addon_version.blockversion.block_type == BlockType.SOFT_BLOCKED
        )
        assert (
            not already_blocked_version.blockversion.block_type
            == BlockType.SOFT_BLOCKED
        )

    def test_soft_block(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        new_addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD - 1
        new_addon = addon_factory(
            guid='any@new', name='New Danger', average_daily_users=new_addon_adu
        )
        partial_addon_adu = new_addon_adu - 1
        partial_addon = addon_factory(
            guid='partial@existing',
            name='Partial Danger',
            average_daily_users=(partial_addon_adu),
        )
        existing_block = block_factory(
            guid=partial_addon.guid,
            # should be updated to addon's adu
            average_daily_users_snapshot=146722437,
            updated_by=user_factory(),
        )
        already_blocked_version = partial_addon.current_version
        new_partial_version = version_factory(addon=partial_addon)
        assert Block.objects.count() == 1
        # Create the block submission
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': ('any@new\npartial@existing\nfull@existing\ninvalid@'),
                'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
                'block_type': BlockType.SOFT_BLOCKED,
                'changed_version_ids': [
                    new_addon.current_version.id,
                    new_partial_version.id,
                ],
                'url': 'dfd',
                'reason': 'some reason',
                'update_url_value': True,
                'update_reason_field': True,
                'delay_days': 0,
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200

        assert Block.objects.count() == 2
        assert BlocklistSubmission.objects.count() == 1
        assert BlocklistSubmission.objects.get().block_type == BlockType.SOFT_BLOCKED

        assert (
            new_addon.current_version.blockversion.block_type == BlockType.SOFT_BLOCKED
        )
        assert new_partial_version.blockversion.block_type == BlockType.SOFT_BLOCKED
        assert already_blocked_version.blockversion.block_type == BlockType.BLOCKED

        todaysdate = datetime.now().date()
        response = self.client.get(
            reverse('admin:blocklist_block_change', args=(existing_block.pk,))
        )
        content = response.content.decode('utf-8')
        assert f'<a href="dfd">{todaysdate}</a>' in content
        assert f'Block edited by {user.name}:\n        {existing_block.guid}' in content
        assert f'versions soft-blocked [{new_partial_version.version}].' in content

        new_block = Block.objects.latest('pk')
        response = self.client.get(
            reverse('admin:blocklist_block_change', args=(new_block.pk,))
        )
        content = response.content.decode('utf-8')
        assert f'<a href="dfd">{todaysdate}</a>' in content
        assert f'Block added by {user.name}:\n        {new_block.guid}' in content
        assert (
            f'versions soft-blocked [{new_addon.current_version.version}].' in content
        )


class TestBlockAdminDelete(TestCase):
    def setUp(self):
        self.delete_url = reverse('admin:blocklist_block_delete_multiple')
        self.submission_url = reverse('admin:blocklist_blocklistsubmission_add')

    def test_delete_input(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        response = self.client.get(self.delete_url, follow=True)
        assert b'Add-on GUIDs (one per line)' in response.content

        # Submit an empty list of guids should redirect back to the page
        response = self.client.post(self.delete_url, {'guids': ''}, follow=False)
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'This field is required' in response.content

        # Any invalid guids should redirect back to the page too, with an error
        block_factory(addon=addon_factory(guid='guid@'), updated_by=user_factory())
        response = self.client.post(
            self.delete_url, {'guids': 'guid@\n{12345-6789}'}, follow=False
        )
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'Block with GUID {12345-6789} not found' in response.content

        # Valid blocks are redirected to the multiple guid view
        # We're purposely not creating the add-on here to test the edge-case
        # where the addon has been hard-deleted or otherwise doesn't exist.
        block_factory(guid='{12345-6789}', updated_by=user_factory())
        assert Block.objects.count() == 2
        response = self.client.post(
            self.delete_url, {'guids': 'guid@\n{12345-6789}'}, follow=True
        )
        self.assertRedirects(response, self.submission_url, status_code=307)

    def _test_delete_multiple_submit(self, addon_adu):
        """addon_adu is important because whether dual signoff is needed is
        based on what the average_daily_users is."""
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        block_one_ver = block_factory(
            addon=addon_factory(
                guid='guid@', name='Normal', average_daily_users=addon_adu
            ),
            updated_by=user_factory(),
        )
        block_no_addon = block_factory(guid='{12345-6789}', updated_by=user_factory())
        addon_with_two_versions = addon_factory(guid='legacy@')
        # add a new version - we won't unblock the first version
        partial_new_version = version_factory(addon=addon_with_two_versions)
        block_two_ver = block_factory(
            addon=addon_with_two_versions,
            updated_by=user_factory(),
        )

        response = self.client.post(
            self.submission_url,
            {
                'guids': 'guid@\n{12345-6789}\nlegacy@',
                'action': str(BlocklistSubmission.ACTIONS.DELETE),
            },
            follow=True,
        )
        content = response.content.decode('utf-8')
        # meta data for block:
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'Unblock' in content
        assert 'guid@' in content
        assert 'Normal' in content
        assert f'{block_one_ver.addon.average_daily_users} users' in content
        assert '{12345-6789}' in content
        # The fields only used for Add/Change submissions shouldn't be shown
        assert 'id_reason' not in content
        # Check we didn't delete the blocks already
        assert Block.objects.count() == 3
        assert BlocklistSubmission.objects.count() == 0
        assert 'id_delay_days' not in content

        # Create the block submission
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': 'guid@\n{12345-6789}\nlegacy@',
                'action': str(BlocklistSubmission.ACTIONS.DELETE),
                'changed_version_ids': [
                    block_one_ver.addon.current_version.id,
                    partial_new_version.id,
                ],
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        return block_one_ver, block_no_addon, block_two_ver

    def _test_delete_verify(
        self, block_with_addon, block_no_addon, block_two_ver, has_signoff=True
    ):
        assert BlocklistSubmission.objects.count() == 1
        submission = BlocklistSubmission.objects.get()
        block_from_addon = block_with_addon.addon
        assert Block.objects.count() == 1
        assert Block.objects.get() == block_two_ver

        add_log = ActivityLog.objects.for_addons(block_from_addon).last()
        assert add_log.action == amo.LOG.BLOCKLIST_BLOCK_DELETED.id
        assert add_log.arguments == [block_from_addon, block_from_addon.guid, None]
        assert add_log.details['blocked_versions'] == []
        assert add_log.details['removed_versions'] == [
            block_from_addon.current_version.version
        ]
        if has_signoff:
            assert add_log.details['signoff_state'] == 'Approved'
            assert add_log.details['signoff_by'] == submission.signoff_by.id
        else:
            assert add_log.details['signoff_state'] == 'Auto Sign-off'
            assert 'signoff_by' not in add_log.details

        (version_block_log,) = tuple(
            ActivityLog.objects.for_versions(block_from_addon.current_version)
        )
        assert version_block_log.action == amo.LOG.BLOCKLIST_VERSION_UNBLOCKED.id
        assert version_block_log.arguments == [block_from_addon.current_version, None]

        assert submission.input_guids == ('guid@\n{12345-6789}\nlegacy@')

        assert submission.to_block == [
            {
                'guid': 'guid@',
                'id': block_with_addon.id,
                'average_daily_users': block_from_addon.average_daily_users,
            },
            {
                'guid': 'legacy@',
                'id': block_two_ver.id,
                'average_daily_users': block_two_ver.addon.average_daily_users,
            },
            {
                'guid': '{12345-6789}',
                'id': block_no_addon.id,
                'average_daily_users': -1,
            },
        ]
        assert list(submission.block_set.all()) == [block_two_ver]

    def test_submit_no_dual_signoff(self):
        addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        (
            block_with_addon,
            block_no_addon,
            block_two_ver,
        ) = self._test_delete_multiple_submit(addon_adu=addon_adu)
        self._test_delete_verify(
            block_with_addon, block_no_addon, block_two_ver, has_signoff=False
        )

    def test_submit_dual_signoff(self):
        addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD + 1
        (
            block_with_addon,
            block_no_addon,
            block_two_ver,
        ) = self._test_delete_multiple_submit(addon_adu=addon_adu)
        # Blocks shouldn't have been deleted yet
        assert Block.objects.count() == 3, Block.objects.all()

        submission = BlocklistSubmission.objects.get()
        submission.update(
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.APPROVED,
            signoff_by=user_factory(),
        )
        assert submission.is_submission_ready
        submission.delete_block_objects()
        self._test_delete_verify(
            block_with_addon, block_no_addon, block_two_ver, has_signoff=True
        )

    def test_version_checkboxes(self):
        # Note this is similar to the test in BlocklistSubmission for add action,
        # but with the logic around what versions are available to select switched
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)

        addon = addon_factory(guid='guid@', average_daily_users=100)
        ver = addon.current_version
        ver_add_subm = version_factory(addon=addon)
        add_submission = BlocklistSubmission.objects.create(
            input_guids=addon.guid, changed_version_ids=[ver_add_subm.id]
        )
        other_addon = addon_factory(average_daily_users=99)
        ver_del_subm = other_addon.current_version
        del_submission = BlocklistSubmission.objects.create(
            input_guids=other_addon.guid,
            changed_version_ids=[ver_del_subm.id],
            action=BlocklistSubmission.ACTIONS.DELETE,
        )
        ver_deleted = version_factory(addon=other_addon, deleted=True)
        ver_block = version_factory(addon=other_addon)
        ver_soft_block = version_factory(addon=other_addon)
        block_factory(
            addon=addon,
            updated_by=user,
            version_ids=[ver_del_subm.id, ver_block.id, ver_soft_block.id],
        )
        ver_soft_block.blockversion.update(block_type=BlockType.SOFT_BLOCKED)
        response = self.client.get(
            self.submission_url,
            {
                'guids': f'{addon.guid}\n {other_addon.guid}\n',
                'action': BlocklistSubmission.ACTIONS.DELETE,
            },
        )
        doc = pq(response.content.decode('utf-8'))
        checkboxes = doc('input[name=changed_version_ids]')

        assert len(checkboxes) == 2

        check_checkbox(checkboxes[0], ver_block)
        assert (
            checkboxes[0].getparent().text_content().strip()
            == f'Unblock {ver_block.version} (🛑 Hard-Blocked)'
        )
        check_checkbox(checkboxes[1], ver_soft_block)
        assert (
            checkboxes[1].getparent().text_content().strip()
            == f'Unblock {ver_soft_block.version} (⚠️ Soft-Blocked)'
        )

        # not a checkbox because in a submission, green circle because not blocked
        assert doc(f'li[data-version-id="{ver_add_subm.id}"]').text() == (
            f'{ver_add_subm.version} (🟢 Not Blocked) [Edit Submission]'
        )
        # not a checkbox because in a submission, red hexagon because hard blocked
        assert doc(f'li[data-version-id="{ver_del_subm.id}"]').text() == (
            f'{ver_del_subm.version} (🛑 Hard-Blocked) [Edit Submission]'
        )
        # not a checkbox because not blocked, and this is a delete action
        assert doc(f'li[data-version-id="{ver.id}"]').text() == (
            f'{ver.version} (🟢 Not Blocked)'
        )
        # not a checkbox because not blocked, and this is a delete action
        assert doc(f'li[data-version-id="{ver_deleted.id}"]').text() == (
            f'{ver_deleted.version} (🟢 Not Blocked)'
        )

        # block_type isn't shown because on a deletion action, it doesn't make
        # sense, it's per-version, and we have verified that we are displaying
        # whether versions are soft or hard blocked in the checkboxes above.
        assert doc('.field-block_type').text() == ''
        assert not doc('.field-block_type select')

        submission_link = doc(f'li[data-version-id="{ver_add_subm.id}"] a')
        assert submission_link.text() == 'Edit Submission'
        assert submission_link.attr['href'] == reverse(
            'admin:blocklist_blocklistsubmission_change',
            args=(add_submission.id,),
        )
        submission_link = doc(f'li[data-version-id="{ver_del_subm.id}"] a')
        assert submission_link.text() == 'Edit Submission'
        assert submission_link.attr['href'] == reverse(
            'admin:blocklist_blocklistsubmission_change',
            args=(del_submission.id,),
        )

    def test_edit_with_delete_submission(self):
        threshold = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        block = block_factory(
            addon=addon_factory(
                guid='guid@', name='Danger Danger', average_daily_users=threshold + 1
            ),
            updated_by=user_factory(),
        )
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@',
            updated_by=user_factory(),
            action=BlocklistSubmission.ACTIONS.DELETE,
        )
        assert mbs.to_block == [
            {
                'guid': 'guid@',
                'id': block.id,
                'average_daily_users': block.addon.average_daily_users,
            }
        ]

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )

        response = self.client.get(multi_url, follow=True)
        assert response.status_code == 200
        assert b'guid@' in response.content
        doc = pq(response.content)
        buttons = doc('.submit-row input')
        assert len(buttons) == 0
        assert b'Reject Submission' not in response.content
        assert b'Approve Submission' not in response.content

    def test_django_delete_redirects_to_bulk(self):
        block = block_factory(
            addon=addon_factory(guid='foo@baa', name='Danger Danger'),
            updated_by=user_factory(),
        )
        django_delete_url = reverse('admin:blocklist_block_delete', args=(block.pk,))

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.force_login(user)
        assert Block.objects.count() == 1

        response = self.client.get(django_delete_url, follow=True)
        self.assertRedirects(
            response,
            self.submission_url + '?guids=foo@baa&action=1',
            target_status_code=200,
        )

        # No immediate delete.
        assert Block.objects.count() == 1

        assert (
            not ActivityLog.objects.for_addons(block.addon)
            .filter(action=amo.LOG.BLOCKLIST_BLOCK_DELETED.id)
            .exists()
        )
        assert (
            not ActivityLog.objects.for_block(block)
            .filter(action=amo.LOG.BLOCKLIST_BLOCK_DELETED.id)
            .exists()
        )

    def test_can_not_delete_without_permission(self):
        block = block_factory(
            addon=addon_factory(guid='foo@baa', name='Danger Danger'),
            updated_by=user_factory(),
        )
        django_delete_url = reverse('admin:blocklist_block_delete', args=(block.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        assert Block.objects.count() == 1

        # Can't access delete confirmation page.
        response = self.client.get(django_delete_url, follow=True)
        assert response.status_code == 403
