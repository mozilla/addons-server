import datetime
import json

from unittest import mock

import django
from django.conf import settings
from django.contrib.admin.models import LogEntry, ADDITION
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import DeniedGuid
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.constants.activity import BLOCKLIST_SIGNOFF

from ..models import Block, BlocklistSubmission


IS_DJANGO_32 = django.VERSION[0] == 3
# django3.2 uses fancy double quotes in its admin logging too
FANCY_QUOTE_OR_DOUBLE_OPEN = '“' if IS_DJANGO_32 else '"'
FANCY_QUOTE_OR_DOUBLE_CLOSE = '”' if IS_DJANGO_32 else '"'
# And sometimes it's a named entity instead, because reasons.
FANCY_QUOTE_OR_ENTITY_OPEN = '“' if IS_DJANGO_32 else '&quot;'
FANCY_QUOTE_OR_ENTITY_CLOSE = '”' if IS_DJANGO_32 else '&quot;'
# Now with a 50% dash length improvement!
LONG_DASH = '—' if IS_DJANGO_32 else '-'


class TestBlockAdmin(TestCase):
    def setUp(self):
        self.admin_home_url = reverse('admin:index')
        self.list_url = reverse('admin:blocklist_block_changelist')
        self.add_url = reverse('admin:blocklist_block_add')
        self.submission_url = reverse('admin:blocklist_blocklistsubmission_add')

    def test_can_see_addon_module_in_admin_with_review_admin(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert modules == ['Blocklist']

    def test_can_not_see_addon_module_in_admin_without_permissions(self):
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert modules == []

    def test_can_list(self):
        addon = addon_factory()
        Block.objects.create(guid=addon.guid, updated_by=user_factory())
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')

    def test_can_not_list_without_permission(self):
        addon = addon_factory()
        Block.objects.create(guid=addon.guid, updated_by=user_factory())
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 403
        assert addon.guid not in response.content.decode('utf-8')

    def test_add(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        response = self.client.get(self.add_url, follow=True)
        assert b'Add-on GUIDs (one per line)' in response.content

        # Submit an empty list of guids should redirect back to the page
        response = self.client.post(self.add_url, {'guids': ''}, follow=False)
        assert b'Add-on GUIDs (one per line)' in response.content

        # A single invalid guid should redirect back to the page too (for now)
        response = self.client.post(self.add_url, {'guids': 'guid@'}, follow=False)
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'Addon with GUID guid@ does not exist' in response.content

        addon = addon_factory(guid='guid@')
        # But should continue to the django admin add page if it exists
        response = self.client.post(self.add_url, {'guids': 'guid@'}, follow=True)
        self.assertRedirects(response, self.submission_url, status_code=307)

        # Multiple guids are redirected to the multiple guid view
        response = self.client.post(
            self.add_url, {'guids': 'guid@\nfoo@baa'}, follow=True
        )
        self.assertRedirects(response, self.submission_url, status_code=307)

        # An existing block will redirect to change view instead
        block = Block.objects.create(guid=addon.guid, updated_by=user_factory())
        response = self.client.post(self.add_url, {'guids': 'guid@'}, follow=True)
        self.assertRedirects(
            response, reverse('admin:blocklist_block_change', args=(block.pk,))
        )

    def test_add_restrictions(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        post_data = {'guids': 'guid@\nfoo@baa'}

        # If the guid already exists in a pending BlocklistSubmission the guid
        # is invalid also
        addon = addon_factory(guid='guid@')
        submission = BlocklistSubmission.objects.create(input_guids='guid@')
        response = self.client.post(self.add_url, post_data, follow=True)
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'GUID guid@ is in a pending Submission' in (response.content)

        # It's okay if the submission isn't pending (rejected, etc) though.
        submission.update(signoff_state=BlocklistSubmission.SIGNOFF_REJECTED)

        # But should continue to the django admin add page if it exists
        response = self.client.post(self.add_url, post_data, follow=True)
        self.assertRedirects(response, self.submission_url, status_code=307)

        # same if one of the guids exists as a block
        block = Block.objects.create(guid=addon.guid, updated_by=user_factory())
        response = self.client.post(self.add_url, post_data, follow=True)
        self.assertRedirects(response, self.submission_url, status_code=307)

        # but not if it's imported from a legacy record
        block.update(legacy_id='343545')
        response = self.client.post(self.add_url, post_data, follow=True)
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'The block for GUID guid@ is readonly - it must be edited' in (
            response.content
        )

        # unless the `blocklist_legacy_submit` waffle switch is on
        with override_switch('blocklist_legacy_submit', active=True):
            response = self.client.post(self.add_url, post_data, follow=True)
            self.assertRedirects(response, self.submission_url, status_code=307)

    def test_add_from_addon_pk_view(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        addon = addon_factory()
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

        # GET params are passed along
        version = addon.current_version
        response = self.client.post(
            url + f'?min_version={version.version}', follow=True
        )
        self.assertRedirects(
            response,
            self.submission_url + f'?guids={addon.guid}&min_version={version.version}',
        )

        # And version ids as short params are expanded and passed along
        response = self.client.post(url + f'?max={version.pk}', follow=True)
        self.assertRedirects(
            response,
            self.submission_url + f'?guids={addon.guid}&max_version={version.version}',
        )
        assert not response.context['messages']

        # Existing blocks are redirected to the change view instead
        block = Block.objects.create(addon=addon, updated_by=user_factory())
        response = self.client.post(url + f'?max={version.pk}', follow=True)
        self.assertRedirects(
            response, reverse('admin:blocklist_block_change', args=(block.pk,))
        )
        # with a message warning the versions were ignored
        assert [msg.message for msg in response.context['messages']] == [
            f'The versions 0 to {version.version} could not be pre-selected '
            'because some versions have been blocked already'
        ]

        # Pending blocksubmissions are redirected to the submission view
        submission = BlocklistSubmission.objects.create(input_guids=addon.guid)
        response = self.client.post(url + f'?max={version.pk}', follow=True)
        self.assertRedirects(
            response,
            reverse(
                'admin:blocklist_blocklistsubmission_change', args=(submission.pk,)
            ),
        )
        # with a message warning the versions were ignored
        assert [msg.message for msg in response.context['messages']] == [
            f'The versions 0 to {version.version} could not be pre-selected '
            'because this addon is part of a pending submission'
        ]

    def test_guid_redirects(self):
        block = Block.objects.create(guid='foo@baa', updated_by=user_factory())
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        response = self.client.post(
            reverse('admin:blocklist_block_change', args=(block.guid,)), follow=True
        )
        self.assertRedirects(
            response,
            reverse('admin:blocklist_block_change', args=(block.pk,)),
            status_code=301,
        )


class TestBlocklistSubmissionAdmin(TestCase):
    def setUp(self):
        self.submission_url = reverse('admin:blocklist_blocklistsubmission_add')
        self.submission_list_url = reverse(
            'admin:blocklist_blocklistsubmission_changelist'
        )
        self.task_user = user_factory(id=settings.TASK_USER_ID)

    def test_add_single(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        deleted_addon = addon_factory(version_kw={'version': '1.2.5'})
        deleted_addon_version = deleted_addon.current_version
        deleted_addon.delete()
        deleted_addon.addonguid.update(guid='guid@')
        addon = addon_factory(
            guid='guid@', name='Danger Danger', version_kw={'version': '1.2a'}
        )
        first_version = addon.current_version
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
        assert str(addon.average_daily_users) in content
        assert Block.objects.count() == 0  # Check we didn't create it already
        assert 'Block History' in content

        # Create the block
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': 'guid@',
                'action': '0',
                'min_version': '0',
                'max_version': addon.current_version.version,
                'existing_min_version': '0',
                'existing_max_version': addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert Block.objects.count() == 1
        block = Block.objects.first()
        assert block.addon == addon
        logs = ActivityLog.objects.for_addons(addon)
        # Multiple versions rejection somehow forces us to go through multiple
        # add-on status updates, it all turns out to be ok in the end though...
        log = logs[0]
        assert log.action == amo.LOG.CHANGE_STATUS.id
        log = logs[1]
        assert log.action == amo.LOG.CHANGE_STATUS.id
        log = logs[2]
        assert log.action == amo.LOG.REJECT_VERSION.id
        log = logs[3]
        assert log.action == amo.LOG.REJECT_VERSION.id
        log = logs[4]
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert log.arguments == [addon, addon.guid, block]
        assert log.details['min_version'] == '0'
        assert log.details['max_version'] == addon.current_version.version
        assert log.details['reason'] == 'some reason'
        block_log = (
            ActivityLog.objects.for_block(block).filter(action=log.action).first()
        )
        assert block_log == log
        block_log_by_guid = (
            ActivityLog.objects.for_guidblock('guid@').filter(action=log.action).first()
        )
        assert block_log_by_guid == log

        assert log == ActivityLog.objects.for_versions(first_version).last()
        assert log == ActivityLog.objects.for_versions(second_version).last()
        assert log == ActivityLog.objects.for_versions(deleted_addon_version).last()
        assert not ActivityLog.objects.for_versions(pending_version).exists()
        assert [msg.message for msg in response.context['messages']] == [
            f'The blocklist submission {FANCY_QUOTE_OR_DOUBLE_OPEN}No Sign-off: guid@; '
            f'dfd; some reason{FANCY_QUOTE_OR_DOUBLE_CLOSE} was added successfully.'
        ]

        response = self.client.get(
            reverse('admin:blocklist_block_change', args=(block.pk,))
        )
        content = response.content.decode('utf-8')
        todaysdate = datetime.datetime.now().date()
        assert f'<a href="dfd">{todaysdate}</a>' in content
        assert f'Block added by {user.name}:\n        guid@' in content
        assert f'versions 0 - {addon.current_version.version}' in content
        assert 'Included in legacy blocklist' not in content

        addon.reload()
        first_version.reload()
        pending_version.reload()
        assert addon.status != amo.STATUS_DISABLED  # not 0 - * so no change
        assert first_version.files.all()[0].status == amo.STATUS_DISABLED
        assert second_version.files.all()[0].status == amo.STATUS_DISABLED
        assert pending_version.files.all()[0].status == (
            amo.STATUS_AWAITING_REVIEW
        )  # no change because not in Block

    @override_switch('blocklist_legacy_submit', active=False)
    def test_legacy_id_property_readonly(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        addon = addon_factory()
        response = self.client.get(
            self.submission_url + f'?guids={addon.guid}', follow=True
        )
        assert not pq(response.content)('#id_legacy_id')
        assert b'_save' in response.content

        # Try to set legacy_id
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': addon.guid,
                'action': '0',
                'min_version': addon.current_version.version,
                'max_version': addon.current_version.version,
                'existing_min_version': addon.current_version.version,
                'existing_max_version': addon.current_version.version,
                'url': '',
                'legacy_id': True,
                'reason': 'Added!',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert BlocklistSubmission.objects.exists()
        assert Block.objects.exists()
        block = Block.objects.get()
        assert block.reason == 'Added!'
        assert block.in_legacy_blocklist is False
        assert BlocklistSubmission.objects.get().in_legacy_blocklist is False

    @override_switch('blocklist_legacy_submit', active=True)
    @mock.patch('olympia.blocklist.models.legacy_delete_blocks')
    @mock.patch('olympia.blocklist.models.legacy_publish_blocks')
    def test_legacy_id_enabled_with_legacy_submit_waffle_on(
        self, publish_mock, delete_mock
    ):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        addon = addon_factory()
        response = self.client.get(
            self.submission_url + f'?guids={addon.guid}', follow=True
        )
        assert pq(response.content)('#id_legacy_id')
        assert b'_save' in response.content

        # Try to set legacy_id
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': addon.guid,
                'action': '0',
                'min_version': addon.current_version.version,
                'max_version': addon.current_version.version,
                'existing_min_version': addon.current_version.version,
                'existing_max_version': addon.current_version.version,
                'url': '',
                'legacy_id': True,
                'reason': 'Added!',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert BlocklistSubmission.objects.exists()
        assert Block.objects.exists()
        block = Block.objects.get()
        assert block.reason == 'Added!'
        publish_mock.assert_called_once()
        delete_mock.assert_not_called()

        # And again with the opposite
        publish_mock.reset_mock()
        addon = addon_factory()
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': addon.guid,
                'action': '0',
                'min_version': addon.current_version.version,
                'max_version': addon.current_version.version,
                'url': '',
                'reason': 'Added again!',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        block = Block.objects.latest()
        assert block.reason == 'Added again!'
        publish_mock.assert_not_called()
        delete_mock.assert_called_once()

    def _test_add_multiple_submit(self, addon_adu):
        """addon_adu is important because whether dual signoff is needed is
        based on what the average_daily_users is."""
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        new_addon_adu = addon_adu
        new_addon = addon_factory(
            guid='any@new', name='New Danger', average_daily_users=new_addon_adu
        )
        existing_and_full = Block.objects.create(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            min_version='0',
            max_version='*',
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
        existing_and_partial = Block.objects.create(
            addon=partial_addon,
            min_version='1',
            max_version='99',
            # should be updated to addon's adu
            average_daily_users_snapshot=146722437,
            updated_by=user_factory(),
        )
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
        assert '2 Add-on GUIDs with {:,} users:'.format(total_adu) in content
        assert 'any@new' in content
        assert 'New Danger' in content
        assert str(new_addon.average_daily_users) in content
        assert 'partial@existing' in content
        assert 'Partial Danger' in content
        assert str(partial_addon.average_daily_users) in content
        # but not for existing blocks already 0 - *
        assert 'full@existing' in content
        assert 'Full Danger' not in content
        assert str(existing_and_full.addon.average_daily_users) not in content
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
                'action': '0',
                'min_version': '0',
                'max_version': '*',
                'existing_min_version': '0',
                'existing_max_version': '*',
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        return (new_addon, existing_and_full, partial_addon, existing_and_partial)

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

        new_block = all_blocks[2]
        assert new_block.addon == new_addon
        assert new_block.average_daily_users_snapshot == new_block.current_adu
        logs = list(
            ActivityLog.objects.for_addons(new_addon).exclude(
                action=amo.LOG.BLOCKLIST_SIGNOFF.id
            )
        )
        change_status_log = logs[0]
        reject_log = logs[1]
        add_log = logs[2]
        assert add_log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert add_log.arguments == [new_addon, new_addon.guid, new_block]
        assert add_log.details['min_version'] == '0'
        assert add_log.details['max_version'] == '*'
        assert add_log.details['reason'] == 'some reason'
        if has_signoff:
            assert add_log.details['signoff_state'] == 'Approved'
            assert add_log.details['signoff_by'] == submission.signoff_by.id
        else:
            assert add_log.details['signoff_state'] == 'No Sign-off'
            assert 'signoff_by' not in add_log.details
        block_log = (
            ActivityLog.objects.for_block(new_block)
            .filter(action=add_log.action)
            .last()
        )
        assert block_log == add_log
        assert (
            add_log
            == ActivityLog.objects.for_versions(new_addon.current_version).last()
        )
        assert reject_log.action == amo.LOG.REJECT_VERSION.id
        assert reject_log.arguments == [new_addon, new_addon.current_version]
        assert reject_log.user == self.task_user
        assert (
            reject_log
            == ActivityLog.objects.for_versions(new_addon.current_version).first()
        )
        assert change_status_log.action == amo.LOG.CHANGE_STATUS.id

        existing_and_partial = existing_and_partial.reload()
        assert all_blocks[1] == existing_and_partial
        # confirm properties were updated
        assert existing_and_partial.min_version == '0'
        assert existing_and_partial.max_version == '*'
        assert existing_and_partial.reason == 'some reason'
        assert existing_and_partial.url == 'dfd'
        assert existing_and_partial.in_legacy_blocklist is False
        assert existing_and_partial.average_daily_users_snapshot == (
            existing_and_partial.current_adu
        )
        logs = list(
            ActivityLog.objects.for_addons(partial_addon).exclude(
                action=amo.LOG.BLOCKLIST_SIGNOFF.id
            )
        )
        change_status_log = logs[0]
        reject_log = logs[1]
        edit_log = logs[2]
        assert edit_log.action == amo.LOG.BLOCKLIST_BLOCK_EDITED.id
        assert edit_log.arguments == [
            partial_addon,
            partial_addon.guid,
            existing_and_partial,
        ]
        assert edit_log.details['min_version'] == '0'
        assert edit_log.details['max_version'] == '*'
        assert edit_log.details['reason'] == 'some reason'
        if has_signoff:
            assert edit_log.details['signoff_state'] == 'Approved'
            assert edit_log.details['signoff_by'] == submission.signoff_by.id
        else:
            assert edit_log.details['signoff_state'] == 'No Sign-off'
            assert 'signoff_by' not in edit_log.details
        block_log = (
            ActivityLog.objects.for_block(existing_and_partial)
            .filter(action=edit_log.action)
            .first()
        )
        assert block_log == edit_log
        assert (
            edit_log
            == ActivityLog.objects.for_versions(partial_addon.current_version).last()
        )
        assert reject_log.action == amo.LOG.REJECT_VERSION.id
        assert reject_log.arguments == [partial_addon, partial_addon.current_version]
        assert reject_log.user == self.task_user
        assert (
            reject_log
            == ActivityLog.objects.for_versions(partial_addon.current_version).first()
        )
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
        assert submission.min_version == new_block.min_version
        assert submission.max_version == new_block.max_version
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
        new_addon_version.reload()
        assert new_addon.status == amo.STATUS_DISABLED
        assert new_addon_version.files.all()[0].status == amo.STATUS_DISABLED
        partial_addon_version = partial_addon.current_version
        partial_addon.reload()
        partial_addon_version.reload()
        assert partial_addon.status == amo.STATUS_DISABLED
        assert partial_addon_version.files.all()[0].status == (amo.STATUS_DISABLED)

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
        multi.update(
            signoff_state=BlocklistSubmission.SIGNOFF_APPROVED,
            signoff_by=user_factory(),
        )
        assert multi.is_submission_ready
        multi.save_to_block_objects()
        self._test_add_multiple_verify_blocks(
            new_addon, existing_and_full, partial_addon, existing_and_partial
        )

    @override_switch('blocklist_admin_dualsignoff_disabled', active=True)
    def test_add_and_edit_with_different_min_max_versions(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        new_addon = addon_factory(
            guid='any@new', average_daily_users=100, version_kw={'version': '5.56'}
        )
        existing_one_to_ten = Block.objects.create(
            addon=addon_factory(guid='partial@existing'),
            min_version='1',
            max_version='10',
            updated_by=user_factory(),
        )
        existing_zero_to_max = Block.objects.create(
            addon=addon_factory(
                guid='full@existing',
                average_daily_users=99,
                version_kw={'version': '10'},
            ),
            min_version='0',
            max_version='*',
            updated_by=user_factory(),
        )
        # Delete any ActivityLog caused by our creations above to make things
        # easier to test.
        ActivityLog.objects.all().delete()
        response = self.client.post(
            self.submission_url,
            {'guids': 'any@new\npartial@existing\nfull@existing'},
            follow=True,
        )

        # Check we've processed the guids correctly.
        doc = pq(response.content)
        assert 'full@existing' in doc('.field-existing-guids').text()
        assert 'partial@existing' in doc('.field-blocks-to-add').text()
        assert 'any@new' in doc('.field-blocks-to-add').text()

        # Check we didn't create the block already
        assert Block.objects.count() == 2
        assert BlocklistSubmission.objects.count() == 0

        # Change the min/max versions
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': ('any@new\npartial@existing\nfull@existing'),
                'action': '0',
                'min_version': '1',  # this is the field we can change
                'max_version': '10',  # this is the field we can change
                'existing_min_version': '0',  # this is a hidden field
                'existing_max_version': '*',  # this is a hidden field
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert b'Blocks to be updated are different' in response.content
        # No Block should have been changed or added
        assert Block.objects.count() == 2
        assert BlocklistSubmission.objects.count() == 0

        # The guids should have been processed differently now
        doc = pq(response.content)
        assert 'partial@existing' in doc('.field-existing-guids').text()
        assert 'full@existing' in doc('.field-blocks-to-add').text()
        assert 'any@new' in doc('.field-blocks-to-add').text()

        # We're submitting again, but now existing_min|max_version is the same
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': ('any@new\npartial@existing\nfull@existing'),
                'action': '0',
                'min_version': '1',  # this is the field we can change
                'max_version': '10',  # this is the field we can change
                'existing_min_version': '1',  # this is a hidden field
                'existing_max_version': '10',  # this is a hidden field
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True,
        )

        assert [msg.message for msg in response.context['messages']] == [
            'The blocklist submission '
            f'{FANCY_QUOTE_OR_DOUBLE_OPEN}No Sign-off: any@new, partial@existing, '
            f'full@exist...; dfd; some reason{FANCY_QUOTE_OR_DOUBLE_CLOSE} was added '
            'successfully.'
        ]

        # This time the blocks are updated
        assert Block.objects.count() == 3
        assert BlocklistSubmission.objects.count() == 1
        all_blocks = Block.objects.all()

        new_block = all_blocks[2]
        assert new_block.addon == new_addon
        logs = ActivityLog.objects.for_addons(new_addon)
        assert logs[0].action == amo.LOG.CHANGE_STATUS.id
        assert logs[1].action == amo.LOG.REJECT_VERSION.id
        log = logs[2]
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert log.arguments == [new_addon, new_addon.guid, new_block]
        assert log.details['min_version'] == '1'
        assert log.details['max_version'] == '10'
        assert log.details['reason'] == 'some reason'
        block_log = (
            ActivityLog.objects.for_block(new_block).filter(action=log.action).last()
        )
        assert block_log == log
        vlog = ActivityLog.objects.for_versions(new_addon.current_version).last()
        assert vlog == log

        existing_zero_to_max = existing_zero_to_max.reload()
        assert all_blocks[1] == existing_zero_to_max
        # confirm properties were updated
        assert existing_zero_to_max.min_version == '1'
        assert existing_zero_to_max.max_version == '10'
        assert existing_zero_to_max.reason == 'some reason'
        assert existing_zero_to_max.url == 'dfd'
        assert existing_zero_to_max.in_legacy_blocklist is False
        logs = ActivityLog.objects.for_addons(existing_zero_to_max.addon)
        assert logs[0].action == amo.LOG.CHANGE_STATUS.id
        assert logs[1].action == amo.LOG.REJECT_VERSION.id
        log = logs[2]
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_EDITED.id
        assert log.arguments == [
            existing_zero_to_max.addon,
            existing_zero_to_max.guid,
            existing_zero_to_max,
        ]
        assert log.details['min_version'] == '1'
        assert log.details['max_version'] == '10'
        assert log.details['reason'] == 'some reason'
        block_log = (
            ActivityLog.objects.for_block(existing_zero_to_max)
            .filter(action=log.action)
            .last()
        )
        assert block_log == log
        vlog = ActivityLog.objects.for_versions(
            existing_zero_to_max.addon.current_version
        ).last()
        assert vlog == log

        existing_one_to_ten = existing_one_to_ten.reload()
        assert all_blocks[0] == existing_one_to_ten
        # confirm properties *were not* updated.
        assert existing_one_to_ten.reason != 'some reason'
        assert existing_one_to_ten.url != 'dfd'
        assert existing_one_to_ten.in_legacy_blocklist is False
        assert not ActivityLog.objects.for_addons(existing_one_to_ten.addon).exists()
        assert not ActivityLog.objects.for_versions(
            existing_one_to_ten.addon.current_version
        ).exists()

        submission = BlocklistSubmission.objects.get()
        assert submission.input_guids == ('any@new\npartial@existing\nfull@existing')
        assert submission.min_version == new_block.min_version
        assert submission.max_version == new_block.max_version
        assert submission.url == new_block.url
        assert submission.reason == new_block.reason

        assert submission.to_block == [
            {
                'guid': 'any@new',
                'id': None,
                'average_daily_users': new_addon.average_daily_users,
            },
            {
                'guid': 'full@existing',
                'id': existing_zero_to_max.id,
                'average_daily_users': existing_zero_to_max.addon.average_daily_users,
            },
        ]
        assert set(submission.block_set.all()) == {new_block, existing_zero_to_max}

        # check versions were disabled (and addons not, because not 0 -*)
        new_addon_version = new_addon.current_version
        new_addon.reload()
        zero_to_max_version = existing_zero_to_max.addon.current_version
        existing_zero_to_max.addon.reload()
        assert new_addon.status != amo.STATUS_DISABLED
        assert existing_zero_to_max.addon.status != amo.STATUS_DISABLED
        assert new_addon_version.files.all()[0].status == amo.STATUS_DISABLED
        assert zero_to_max_version.files.all()[0].status == amo.STATUS_DISABLED

    @mock.patch('olympia.blocklist.admin.GUID_FULL_LOAD_LIMIT', 1)
    def test_add_multiple_bulk_so_fake_block_objects(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        new_addon = addon_factory(guid='any@new', name='New Danger')
        Block.objects.create(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            min_version='0',
            max_version='*',
            legacy_id='34345',
            updated_by=user_factory(),
        )
        partial_addon = addon_factory(guid='partial@existing', name='Partial Danger')
        Block.objects.create(
            addon=partial_addon,
            min_version='1',
            max_version='99',
            legacy_id='75456',
            updated_by=user_factory(),
        )
        Block.objects.create(
            addon=addon_factory(guid='regex@legacy'),
            min_version='23',
            max_version='567',
            legacy_id='*regexlegacy',
            updated_by=user_factory(),
        )
        response = self.client.post(
            self.submission_url,
            {
                'guids': 'any@new\npartial@existing\nfull@existing\ninvalid@\n'
                'regex@legacy'
            },
            follow=True,
        )
        content = response.content.decode('utf-8')
        # This metadata should exist
        assert new_addon.guid in content
        assert str(new_addon.average_daily_users) in content
        assert partial_addon.guid in content
        assert str(partial_addon.average_daily_users) in content
        assert 'full@existing' in content
        assert 'invalid@' in content

        assert 'regex@legacy' in content
        assert 'imported from a regex based legacy' in content
        assert 'regex@legacy' in pq(response.content)('.regexlegacywarning').text()
        assert 'full@existing' not in pq(response.content)('.regexlegacywarning').text()

        # But Addon names or review links shouldn't have been loaded
        assert 'New Danger' not in content
        assert 'Partial Danger' not in content
        assert 'Full Danger' not in content
        assert 'Review Listed' not in content
        assert 'Review Unlisted' not in content

    def test_legacy_regex_warning(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        new_addon = addon_factory(guid='any@new', name='New Danger')
        Block.objects.create(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            min_version='0',
            max_version='*',
            legacy_id='5656',
            updated_by=user_factory(),
        )
        partial_addon = addon_factory(guid='partial@existing', name='Partial Danger')
        Block.objects.create(
            addon=partial_addon,
            min_version='1',
            max_version='99',
            legacy_id='74356',
            updated_by=user_factory(),
        )
        Block.objects.create(
            addon=addon_factory(guid='regex@legacy'),
            min_version='23',
            max_version='567',
            legacy_id='*regexlegacy',
            updated_by=user_factory(),
        )
        response = self.client.post(
            self.submission_url,
            {
                'guids': 'any@new\npartial@existing\nfull@existing\ninvalid@\n'
                'regex@legacy'
            },
            follow=True,
        )
        content = response.content.decode('utf-8')
        # This metadata should exist
        assert new_addon.guid in content
        assert str(new_addon.average_daily_users) in content
        assert partial_addon.guid in content
        assert str(partial_addon.average_daily_users) in content
        assert 'full@existing' in content
        assert 'invalid@' in content

        assert 'regex@legacy' in content
        assert 'imported from a regex based legacy' in content
        assert 'regex@legacy' in pq(response.content)('.regexlegacywarning').text()
        assert 'full@existing' not in pq(response.content)('.regexlegacywarning').text()

    def test_review_links(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        post_kwargs = {
            'path': self.submission_url,
            'data': {'guids': 'guid@\nfoo@baa\ninvalid@'},
            'follow': True,
        }

        # An addon with only listed versions should have listed link
        addon = addon_factory(
            guid='guid@', name='Danger Danger', version_kw={'version': '0.1'}
        )
        # This is irrelevant because a complete block doesn't have links
        Block.objects.create(
            addon=addon_factory(guid='foo@baa'),
            min_version='0',
            max_version='*',
            updated_by=user_factory(),
        )
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' not in response.content
        assert b'Edit Block' not in response.content
        assert not pq(response.content)('.existing_block')

        # Should work the same if partial block (exists but needs updating)
        existing_block = Block.objects.create(
            guid=addon.guid, min_version='8', updated_by=user_factory()
        )
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' not in response.content
        assert pq(response.content)('.existing_block a').attr('href') == (
            reverse('admin:blocklist_block_change', args=(existing_block.pk,))
        )
        assert pq(response.content)('.existing_block').text() == (
            '[Edit Block: %s - %s]' % (existing_block.min_version, '*')
        )

        # And an unlisted version
        version_factory(
            addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED, version='0.2'
        )
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' in response.content
        assert pq(response.content)('.existing_block a').attr('href') == (
            reverse('admin:blocklist_block_change', args=(existing_block.pk,))
        )
        assert pq(response.content)('.existing_block').text() == (
            '[Edit Block: %s - %s]' % (existing_block.min_version, '*')
        )

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

    def test_can_not_set_min_version_above_max_version(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        addon_factory(guid='any@new', name='New Danger')
        partial_addon = addon_factory(guid='partial@existing', name='Partial Danger')
        Block.objects.create(
            addon=partial_addon,
            min_version='1',
            max_version='99',
            updated_by=user_factory(),
        )
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': 'any@new\npartial@existing\ninvalid@',
                'action': '0',
                'min_version': '5',
                'max_version': '3',
                'existing_min_version': '5',
                'existing_max_version': '3',
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert b'Min version can not be greater than Max' in response.content
        assert Block.objects.count() == 1

    def test_can_not_add_without_create_permission(self):
        user = user_factory(email='someone@mozilla.com')
        # The signoff permission shouldn't be sufficient
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.login(email=user.email)

        addon_factory(guid='guid@', name='Danger Danger')
        existing = Block.objects.create(
            addon=addon_factory(guid='foo@baa'),
            min_version='1',
            max_version='99',
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
                'action': '0',
                'min_version': '0',
                'max_version': '*',
                'existing_min_version': '0',
                'existing_max_version': '*',
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 403
        assert Block.objects.count() == 1
        existing = existing.reload()
        assert existing.min_version == '1'  # check the values didn't update.

    def _test_can_list_with_permission(self, permission):
        # add some guids to the multi block to test out the counts in the list
        addon = addon_factory(guid='guid@', name='Danger Danger')
        block = Block.objects.create(
            addon=addon_factory(
                guid='block@', name='High Voltage', average_daily_users=1
            ),
            updated_by=user_factory(),
        )
        add_change_subm = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@\nblock@',
            updated_by=user_factory(display_name='Bób'),
            min_version='123',
            action=BlocklistSubmission.ACTION_ADDCHANGE,
        )
        delete_subm = BlocklistSubmission.objects.create(
            input_guids='block@',
            updated_by=user_factory(display_name='Sué'),
            action=BlocklistSubmission.ACTION_DELETE,
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
        self.client.login(email=user.email)

        response = self.client.get(self.submission_list_url, follow=True)
        assert response.status_code == 200
        assert 'Bób' in response.content.decode('utf-8')
        assert 'Sué' in response.content.decode('utf-8')
        doc = pq(response.content)
        assert doc('th.field-blocks_count').text() == '1 add-ons 2 add-ons'
        assert doc('.field-action').text() == ('Delete Add/Change')
        assert doc('.field-signoff_state').text() == 'Pending Pending'

    def test_can_list_with_blocklist_create(self):
        self._test_can_list_with_permission('Blocklist:Create')

    def test_can_list_with_blocklist_signoff(self):
        self._test_can_list_with_permission('Blocklist:Signoff')

    def test_can_not_list_without_permission(self):
        BlocklistSubmission.objects.create(updated_by=user_factory(display_name='Bób'))
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)

        response = self.client.get(self.submission_list_url, follow=True)
        assert response.status_code == 403
        assert 'Bób' not in response.content.decode('utf-8')

    def test_edit_with_blocklist_create(self):
        threshold = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        addon = addon_factory(
            guid='guid@', name='Danger Danger', average_daily_users=threshold + 1
        )
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@\nsecond@invalid', updated_by=user_factory()
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
        self.client.login(email=user.email)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )

        response = self.client.get(multi_url, follow=True)
        assert response.status_code == 200
        assert b'guid@<br>invalid@<br>second@invalid' in response.content
        doc = pq(response.content)
        buttons = doc('.submit-row input')
        assert buttons[0].attrib['value'] == 'Update'
        assert len(buttons) == 1
        assert b'Reject Submission' not in response.content
        assert b'Approve Submission' not in response.content

        response = self.client.post(
            multi_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'min_version': '1',  # should be ignored
                'max_version': '99',  # should be ignored
                'url': 'new.url',
                'reason': 'a new reason thats longer than 40 charactors',
                '_save': 'Update',
            },
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()

        # the read-only values above weren't changed.
        assert mbs.input_guids == 'guid@\ninvalid@\nsecond@invalid'
        assert mbs.min_version == '0'
        assert mbs.max_version == '*'
        # but the other details were
        assert mbs.url == 'new.url'
        assert mbs.reason == 'a new reason thats longer than 40 charactors'

        # The blocklistsubmission wasn't approved or rejected though
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_PENDING
        assert Block.objects.count() == 0

        log_entry = LogEntry.objects.get()
        assert log_entry.user == user
        assert log_entry.object_id == str(mbs.id)
        change_json = json.loads(log_entry.change_message)
        # change_message fields are the Field names rather than the fields in django3.2
        change_json[0]['changed']['fields'] = [
            field.lower() for field in change_json[0]['changed']['fields']
        ]
        assert change_json == [{'changed': {'fields': ['url', 'reason']}}]

        response = self.client.get(multi_url, follow=True)
        assert (
            f'Changed {FANCY_QUOTE_OR_ENTITY_OPEN}Pending: guid@, invalid@, '
            'second@invalid; new.url; a new reason thats longer than 40 cha...'
            in response.content.decode('utf-8')
        )

    def test_edit_page_with_blocklist_signoff(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@\nsecond@invalid', updated_by=user_factory()
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
        self.client.login(email=user.email)
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
                'action': '1',
                'min_version': '1',
                'max_version': '99',
                'url': 'new.url',
                'reason': 'a reason',
                '_save': 'Update',
            },
            follow=True,
        )
        assert response.status_code == 403
        mbs = mbs.reload()

        # none of the values above were changed because they're all read-only.
        assert mbs.input_guids == 'guid@\ninvalid@\nsecond@invalid'
        assert mbs.action == 0
        assert mbs.min_version == '0'
        assert mbs.max_version == '*'
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

        # The blocklistsubmission wasn't approved or rejected either
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_PENDING
        assert Block.objects.count() == 0
        assert LogEntry.objects.count() == 0

    @override_switch('blocklist_legacy_submit', active=True)
    @mock.patch('olympia.blocklist.models.legacy_publish_blocks')
    def test_signoff_approve(self, legacy_publish_blocks_mock):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        version = addon.current_version
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@', updated_by=user_factory(), legacy_id=True
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
        self.client.login(email=user.email)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )
        response = self.client.post(
            multi_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'min_version': '1',  # should be ignored
                'max_version': '99',  # should be ignored
                'url': 'new.url',  # should be ignored
                'reason': 'a reason',  # should be ignored
                '_approve': 'Approve Submission',
            },
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()
        assert mbs.signoff_by == user

        # the read-only values above weren't changed.
        assert mbs.input_guids == 'guid@\ninvalid@'
        assert mbs.min_version == '0'
        assert mbs.max_version == '*'
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

        # As it was signed off, the block should have been created
        assert Block.objects.count() == 1
        new_block = Block.objects.get()

        assert new_block.addon == addon
        logs = ActivityLog.objects.for_addons(addon)
        change_status_log = logs[0]
        reject_log = logs[1]
        signoff_log = logs[2]
        add_log = logs[3]
        assert add_log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert add_log.arguments == [addon, addon.guid, new_block]
        assert add_log.details['min_version'] == '0'
        assert add_log.details['max_version'] == '*'
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
        assert add_log == ActivityLog.objects.for_versions(addon.current_version).last()

        assert signoff_log.action == amo.LOG.BLOCKLIST_SIGNOFF.id
        assert signoff_log.arguments == [addon, addon.guid, 'add', new_block]
        assert signoff_log.user == user

        assert reject_log.action == amo.LOG.REJECT_VERSION.id
        assert reject_log.arguments == [addon, version]
        assert reject_log.user == self.task_user
        assert (
            reject_log
            == ActivityLog.objects.for_versions(addon.current_version).first()
        )

        assert change_status_log.action == amo.LOG.CHANGE_STATUS.id

        # blocks would have been submitted to remote settings legacy collection
        legacy_publish_blocks_mock.assert_called()
        legacy_publish_blocks_mock.assert_called_with([new_block])

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
        other_obj = addon_factory(id=mbs.id)
        LogEntry.objects.log_action(
            user_factory().id,
            ContentType.objects.get_for_model(other_obj).pk,
            other_obj.id,
            repr(other_obj),
            ADDITION,
            'not a Block!',
        )

        response = self.client.get(multi_url, follow=True)
        assert (
            f'Changed {FANCY_QUOTE_OR_ENTITY_OPEN}Approved: guid@, invalid@'
            f'{FANCY_QUOTE_OR_ENTITY_CLOSE} {LONG_DASH} Sign-off Approval'
            in response.content.decode('utf-8')
        )
        assert b'not a Block!' not in response.content

        # we disabled versions and the addon (because 0 - *)
        addon.reload()
        version.reload()
        assert addon.status == amo.STATUS_DISABLED
        assert version.files.all()[0].status == amo.STATUS_DISABLED

    @override_switch('blocklist_legacy_submit', active=True)
    @mock.patch('olympia.blocklist.models.legacy_publish_blocks')
    def test_signoff_reject(self, legacy_publish_blocks_mock):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        version = addon.current_version
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@', updated_by=user_factory()
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
        self.client.login(email=user.email)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )
        response = self.client.post(
            multi_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'min_version': '1',  # should be ignored
                'max_version': '99',  # should be ignored
                'url': 'new.url',  # should be ignored
                'reason': 'a reason',  # should be ignored
                '_reject': 'Reject Submission',
            },
            follow=True,
        )
        assert response.status_code == 200
        mbs = mbs.reload()

        # the read-only values above weren't changed.
        assert mbs.input_guids == 'guid@\ninvalid@'
        assert mbs.min_version == '0'
        assert mbs.max_version == '*'
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

        # blocks would not have been submitted to remote settings legacy
        # collection
        legacy_publish_blocks_mock.assert_not_called()

        # And the blocklistsubmission was rejected, so no Blocks created
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_REJECTED
        assert Block.objects.count() == 0
        assert not mbs.is_submission_ready

        log_entry = LogEntry.objects.last()
        assert log_entry.user == user
        assert log_entry.object_id == str(mbs.id)
        other_obj = addon_factory(id=mbs.id)
        LogEntry.objects.log_action(
            user_factory().id,
            ContentType.objects.get_for_model(other_obj).pk,
            other_obj.id,
            repr(other_obj),
            ADDITION,
            'not a Block!',
        )

        response = self.client.get(multi_url, follow=True)
        content = response.content.decode('utf-8')
        assert (
            f'Changed {FANCY_QUOTE_OR_ENTITY_OPEN}Rejected: guid@, invalid@'
            f'{FANCY_QUOTE_OR_ENTITY_CLOSE} {LONG_DASH} Sign-off Rejection' in content
        )
        assert 'not a Block!' not in content

        # statuses didn't change
        addon.reload()
        version.reload()
        assert addon.status != amo.STATUS_DISABLED
        assert version.files.all()[0].status != amo.STATUS_DISABLED

    def test_cannot_approve_with_only_block_create_permission(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@', updated_by=user_factory()
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
        self.client.login(email=user.email)
        multi_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )
        response = self.client.post(
            multi_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'min_version': '1',  # should be ignored
                'max_version': '99',  # should be ignored
                'url': 'new.url',  # could be updated with this permission
                'reason': 'a reason',  # could be updated with this permission
                '_approve': 'Approve Submission',
            },
            follow=True,
        )
        assert response.status_code == 403
        mbs = mbs.reload()
        # It wasn't signed off
        assert not mbs.signoff_by
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_PENDING
        # And the details weren't updated either
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

    def test_can_only_reject_your_own_with_only_block_create_permission(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        submission = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@', updated_by=user_factory()
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
        self.client.login(email=user.email)
        change_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(submission.id,)
        )
        response = self.client.post(
            change_url,
            {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'min_version': '1',  # should be ignored
                'max_version': '99',  # should be ignored
                'url': 'new.url',  # could be updated with this permission
                'reason': 'a reason',  # could be updated with this permission
                '_reject': 'Reject Submission',
            },
            follow=True,
        )
        assert response.status_code == 403
        submission = submission.reload()
        # It wasn't signed off
        assert not submission.signoff_by
        assert submission.signoff_state == BlocklistSubmission.SIGNOFF_PENDING
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
                'min_version': '1',  # should be ignored
                'max_version': '99',  # should be ignored
                'url': 'new.url',  # could be updated with this permission
                'reason': 'a reason',  # could be updated with this permission
                '_reject': 'Reject Submission',
            },
            follow=True,
        )
        assert response.status_code == 200
        submission = submission.reload()
        assert submission.signoff_state == BlocklistSubmission.SIGNOFF_REJECTED
        assert not submission.signoff_by
        assert submission.url == 'new.url'
        assert submission.reason == 'a reason'

    def test_signed_off_view(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@\ninvalid@\nsecond@invalid',
            updated_by=user_factory(),
            signoff_by=user_factory(),
            signoff_state=BlocklistSubmission.SIGNOFF_APPROVED,
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
        assert mbs.signoff_state == BlocklistSubmission.SIGNOFF_PUBLISHED
        # update addon adu to something different
        assert block.average_daily_users_snapshot == addon.average_daily_users
        addon.update(average_daily_users=1234)

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        multi_view_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(mbs.id,)
        )

        response = self.client.get(multi_view_url, follow=True)
        assert response.status_code == 200
        assert b'guid@<br>invalid@<br>second@invalid' in response.content
        doc = pq(response.content)
        review_link = doc('div.field-blocks div div a')[0]
        assert review_link.attrib['href'] == absolutify(
            reverse('reviewers.review', args=(addon.pk,))
        )
        guid_link = doc('div.field-blocks div div a')[1]
        assert guid_link.attrib['href'] == reverse(
            'admin:blocklist_block_change', args=(block.pk,)
        )
        assert not doc('submit-row input')
        assert str(block.average_daily_users_snapshot) in (
            response.content.decode('utf-8')
        )

    def test_list_filters(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.login(email=user.email)
        addon_factory(guid='pending1@')
        addon_factory(guid='pending2@')
        addon_factory(guid='published@')
        BlocklistSubmission.objects.create(
            input_guids='pending1@\npending2@',
            signoff_state=BlocklistSubmission.SIGNOFF_PENDING,
        )
        BlocklistSubmission.objects.create(
            input_guids='missing@', signoff_state=BlocklistSubmission.SIGNOFF_APPROVED
        )
        BlocklistSubmission.objects.create(
            input_guids='published@',
            signoff_state=BlocklistSubmission.SIGNOFF_PUBLISHED,
        )

        response = self.client.get(self.submission_list_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)

        # default is to only show Pending (signoff_state=0)
        assert doc('#result_list tbody tr').length == 1
        assert doc('.field-blocks_count').text() == '2 add-ons'

        expected_filters = [
            ('All', '?signoff_state=all'),
            ('Pending', '?signoff_state=0'),
            ('Approved', '?signoff_state=1'),
            ('Rejected', '?signoff_state=2'),
            ('No Sign-off', '?signoff_state=3'),
            ('Published to Blocks', '?signoff_state=4'),
        ]
        filters = [(x.text, x.attrib['href']) for x in doc('#changelist-filter a')]
        assert filters == expected_filters
        # Should be shown as selected too
        assert doc('#changelist-filter li.selected a').text() == 'Pending'

        # Repeat with the Pending filter explictly selected
        response = self.client.get(
            self.submission_list_url,
            {
                'signoff_state': 0,
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        assert doc('.field-blocks_count').text() == '2 add-ons'
        assert doc('#changelist-filter li.selected a').text() == 'Pending'

        # And then lastly with all submissions showing
        response = self.client.get(self.submission_list_url, {'signoff_state': 'all'})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 3
        assert doc('#changelist-filter li.selected a').text() == 'All'

    def test_blocked_deleted_keeps_addon_status(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        deleted_addon = addon_factory(guid='guid@', version_kw={'version': '1.2.5'})
        deleted_addon.delete()
        assert deleted_addon.status == amo.STATUS_DELETED
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
                'action': '0',
                'min_version': '0',
                'max_version': '*',
                'existing_min_version': '0',
                'existing_max_version': '*',
                'url': 'dfd',
                'reason': 'some reason',
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


class TestBlockAdminEdit(TestCase):
    def setUp(self):
        self.addon = addon_factory(
            guid='guid@', name='Danger Danger', version_kw={'version': '123.456'}
        )
        self.extra_version = self.addon.current_version
        # note, a lower version, to check it's the number, regardless, that's blocked.
        version_factory(addon=self.addon, version='123')
        self.block = Block.objects.create(
            guid=self.addon.guid,
            updated_by=user_factory(),
            average_daily_users_snapshot=12345678,
        )
        self.change_url = reverse('admin:blocklist_block_change', args=(self.block.pk,))
        self.submission_url = reverse('admin:blocklist_blocklistsubmission_add')
        # We need the task user because some test cases eventually trigger
        # `disable_addon_for_block()`.
        user_factory(id=settings.TASK_USER_ID)

    def _test_edit(self, user, signoff_state):
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert str(12345678) in content
        assert 'Block History' in content
        assert 'imported from a regex based legacy' not in content

        # Change the block
        response = self.client.post(
            self.change_url,
            {
                'addon_id': addon_factory().id,  # new addon should be ignored
                'input_guids': self.block.guid,
                'action': '0',
                'min_version': '0',
                'max_version': self.addon.current_version.version,
                'url': 'https://foo.baa',
                'reason': 'some other reason',
                '_continue': 'Save and continue editing',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert BlocklistSubmission.objects.exists()
        submission = BlocklistSubmission.objects.get(input_guids=self.block.guid)
        assert submission.signoff_state == signoff_state

    def _test_post_edit_logging(self, user, blocked_version_changes=True):
        assert Block.objects.count() == 1  # check we didn't create another
        block = Block.objects.first()
        assert block.addon == self.addon  # wasn't changed
        assert block.max_version == '123'
        reject_log, edit_log = list(
            ActivityLog.objects.for_addons(self.addon).exclude(
                action=BLOCKLIST_SIGNOFF.id
            )
        )
        assert edit_log.action == amo.LOG.BLOCKLIST_BLOCK_EDITED.id
        assert edit_log.arguments == [self.addon, self.addon.guid, self.block]
        assert edit_log.details['min_version'] == '0'
        assert edit_log.details['max_version'] == self.addon.current_version.version
        assert edit_log.details['reason'] == 'some other reason'
        block_log = (
            ActivityLog.objects.for_block(self.block)
            .filter(action=amo.LOG.BLOCKLIST_BLOCK_EDITED.id)
            .last()
        )
        assert block_log == edit_log
        block_log_by_guid = (
            ActivityLog.objects.for_guidblock('guid@')
            .filter(action=amo.LOG.BLOCKLIST_BLOCK_EDITED.id)
            .last()
        )
        assert block_log_by_guid == edit_log
        current_version_log = ActivityLog.objects.for_versions(
            self.addon.current_version
        ).last()
        assert current_version_log == edit_log
        assert block.is_version_blocked(self.addon.current_version.version)
        if blocked_version_changes:
            extra_version_log = ActivityLog.objects.for_versions(
                self.extra_version
            ).last()
            # should have a block entry for the version even though it's now not blocked
            assert extra_version_log == edit_log
            assert not block.is_version_blocked(self.extra_version.version)

        assert reject_log.action == amo.LOG.REJECT_VERSION.id

        # Check the block history contains the edit just made.
        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        todaysdate = datetime.datetime.now().date()
        assert f'<a href="https://foo.baa">{todaysdate}</a>' in content
        assert f'Block edited by {user.name}:\n        {self.block.guid}' in (content)
        assert f'versions 0 - {self.addon.current_version.version}' in content
        assert 'Included in legacy blocklist' not in content

    def test_edit_low_adu(self):
        user = user_factory(email='someone@mozilla.com')
        self.addon.update(
            average_daily_users=(settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD)
        )
        self._test_edit(user, BlocklistSubmission.SIGNOFF_PUBLISHED)
        self._test_post_edit_logging(user)

    def test_edit_high_adu(self):
        user = user_factory(email='someone@mozilla.com')
        self.addon.update(
            average_daily_users=(
                settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD + 1
            )
        )
        self._test_edit(user, BlocklistSubmission.SIGNOFF_PENDING)
        submission = BlocklistSubmission.objects.get(input_guids=self.block.guid)
        submission.update(
            signoff_state=BlocklistSubmission.SIGNOFF_APPROVED,
            signoff_by=user_factory(),
        )
        submission.save_to_block_objects()
        self._test_post_edit_logging(user)

    def test_edit_high_adu_only_metadata(self):
        user = user_factory(email='someone@mozilla.com')
        self.addon.update(
            average_daily_users=(
                settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD + 1
            )
        )
        self.block.update(max_version=self.addon.current_version.version)
        self._test_edit(user, BlocklistSubmission.SIGNOFF_PUBLISHED)
        self._test_post_edit_logging(user, blocked_version_changes=False)

    def test_invalid_versions_not_accepted(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        deleted_addon = addon_factory(version_kw={'version': '345.34a'})
        deleted_addon.delete()
        deleted_addon.addonguid.update(guid=self.addon.guid)
        self.extra_version.update(version='123.4b5')
        self.addon.current_version.update(version='678')
        # Update min_version in self.block to a version that doesn't exist
        self.block.update(min_version='444.4a')

        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        doc = pq(content)
        ver_list = doc('#id_min_version option')
        assert len(ver_list) == 5
        assert ver_list.eq(0).attr['value'] == '444.4a'
        assert ver_list.eq(0).text() == '(invalid)'
        assert ver_list.eq(1).attr['value'] == '0'
        assert ver_list.eq(2).attr['value'] == '123.4b5'
        assert ver_list.eq(3).attr['value'] == '678'
        assert ver_list.eq(4).attr['value'] == '345.34a'
        ver_list = doc('#id_max_version option')
        assert len(ver_list) == 4
        assert ver_list.eq(0).attr['value'] == '*'
        assert ver_list.eq(1).attr['value'] == '123.4b5'
        assert ver_list.eq(2).attr['value'] == '678'
        assert ver_list.eq(3).attr['value'] == '345.34a'

        data = {
            'input_guids': self.block.guid,
            'action': '0',
            'url': 'https://foo.baa',
            'reason': 'some other reason',
            '_save': 'Update',
        }
        # Try saving the form with the same min_version
        response = self.client.post(
            self.change_url,
            dict(
                min_version='444.4a',  # current value, but not a version.
                max_version=self.addon.current_version.version,  # valid
                **data,
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert b'Invalid version' in response.content
        self.block = self.block.reload()
        assert self.block.min_version == '444.4a'  # not changed
        assert self.block.max_version == '*'  # not changed either.
        assert not ActivityLog.objects.for_addons(self.addon).exists()
        doc = pq(content)
        assert doc('#id_min_version option').eq(0).attr['value'] == '444.4a'

        # Change to a version that exists
        response = self.client.post(
            self.change_url,
            dict(min_version='345.34a', max_version='*', **data),
            follow=True,
        )
        assert response.status_code == 200
        assert b'Invalid version' not in response.content
        self.block = self.block.reload()
        assert self.block.min_version == '345.34a'  # changed
        assert self.block.max_version == '*'
        assert ActivityLog.objects.for_addons(self.addon).exists()
        # the value shouldn't be in the list of versions either any longer.
        assert b'444.4a' not in response.content

    def test_can_not_edit_without_permission(self):
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)

        response = self.client.get(self.change_url, follow=True)
        assert response.status_code == 403
        assert b'Danger Danger' not in response.content

        # Try to edit the block anyway
        response = self.client.post(
            self.change_url,
            {
                'input_guids': self.block.guid,
                'min_version': '0',
                'max_version': self.addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 403
        assert Block.objects.count() == 1

    def test_cannot_edit_when_guid_in_blocklistsubmission_change(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        blocksubm = BlocklistSubmission.objects.create(
            input_guids=self.block.guid, min_version='123.45'
        )
        assert blocksubm.to_block == [
            {
                'id': self.block.id,
                'guid': self.block.guid,
                'average_daily_users': self.block.addon.average_daily_users,
            }
        ]

        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert 'Add/Change submission pending' in content
        submission_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(blocksubm.id,)
        )
        assert 'min_version: "0" to "123.45"' in content
        assert submission_url in content
        assert 'Close' in content
        assert '_save' not in content
        assert 'deletelink' not in content

        # Try to edit the block anyway
        response = self.client.post(
            self.change_url,
            {
                'input_guids': self.block.guid,
                'min_version': '0',
                'max_version': self.addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 403
        assert self.block.max_version == '*'  # not changed

    def test_cannot_edit_when_guid_in_blocklistsubmission_delete(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        blocksubm = BlocklistSubmission.objects.create(
            input_guids=self.block.guid, action=BlocklistSubmission.ACTION_DELETE
        )
        assert blocksubm.to_block == [
            {
                'id': self.block.id,
                'guid': self.block.guid,
                'average_daily_users': self.block.addon.average_daily_users,
            }
        ]

        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert 'Delete submission pending' in content
        submission_url = reverse(
            'admin:blocklist_blocklistsubmission_change', args=(blocksubm.id,)
        )
        assert submission_url in content
        assert 'Close' in content
        assert '_save' not in content
        assert 'deletelink' not in content

        # Try to edit the block anyway
        response = self.client.post(
            self.change_url,
            {
                'input_guids': self.block.guid,
                'min_version': '0',
                'max_version': self.addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 403
        assert self.block.max_version == '*'  # not changed

    def test_imported_regex_block(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        self.block.update(legacy_id='*foo@baa')

        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert str(12345678) in content
        assert 'Block History' in content
        assert 'imported from a regex based legacy' in content

    @override_switch('blocklist_legacy_submit', active=False)
    def test_cannot_edit_when_imported_block(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        self.block.update(legacy_id='123456')

        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert 'Close' in content
        assert '_save' not in content
        assert 'deletelink' not in content

        # Try to edit the block anyway
        response = self.client.post(
            self.change_url,
            {
                'input_guids': self.block.guid,
                'action': '0',
                'min_version': '0',
                'max_version': self.addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 403
        assert self.block.max_version == '*'  # not changed

    @override_switch('blocklist_legacy_submit', active=True)
    @mock.patch('olympia.blocklist.models.legacy_publish_blocks')
    def test_can_edit_imported_block_if_legacy_submit_waffle_on(self, pub_mck):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        self.block.update(legacy_id='123456')

        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert 'Close' not in content
        assert '_save' in content
        assert 'deletelink' in content
        assert self.block.in_legacy_blocklist is True

        # We can edit the block
        assert not BlocklistSubmission.objects.exists()
        response = self.client.post(
            self.change_url,
            {
                'input_guids': self.block.guid,
                'action': '0',
                'min_version': '0',
                'max_version': self.addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                'legacy_id': '123456',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert BlocklistSubmission.objects.exists()
        BlocklistSubmission.objects.get(input_guids=self.block.guid)
        pub_mck.assert_called_with([self.block])
        self.block.reload()
        assert self.block.in_legacy_blocklist is True

    @override_switch('blocklist_legacy_submit', active=False)
    def test_legacy_id_property_is_readonly(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        self.block.update(legacy_id='')

        response = self.client.get(self.change_url, follow=True)
        assert pq(response.content)('.field-legacy_id .readonly')
        assert b'_save' in response.content

        assert self.block.in_legacy_blocklist is False
        # Try to edit the block
        response = self.client.post(
            self.change_url,
            {
                'input_guids': self.block.guid,
                'action': '0',
                'min_version': self.block.min_version,
                'max_version': self.block.max_version,
                'url': '',
                'reason': 'Changed!',
                'legacy_id': '34344545',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        self.block.reload()
        assert self.block.reason == 'Changed!'
        assert self.block.in_legacy_blocklist is False

    @override_switch('blocklist_legacy_submit', active=True)
    @mock.patch('olympia.blocklist.models.legacy_delete_blocks')
    def test_legacy_id_is_enabled_with_legacy_submit_waffle_on(self, del_mock):
        del_mock.side_effect = lambda blocks: blocks[0].update(legacy_id='')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        self.block.update(legacy_id='3467635')

        response = self.client.get(self.change_url, follow=True)
        assert pq(response.content)('.field-legacy_id input')
        assert b'_save' in response.content

        # Try to edit the block
        response = self.client.post(
            self.change_url,
            {
                'input_guids': self.block.guid,
                'action': '0',
                'min_version': self.block.min_version,
                'max_version': self.block.max_version,
                'url': '',
                'reason': 'Changed!',
                # no legacy_id so clearing it
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert BlocklistSubmission.objects.exists()
        self.block.reload()
        assert self.block.reason == 'Changed!'
        del_mock.assert_called_with([self.block])
        assert self.block.in_legacy_blocklist is False


class TestBlockAdminDelete(TestCase):
    def setUp(self):
        self.delete_url = reverse('admin:blocklist_block_delete_multiple')
        self.submission_url = reverse('admin:blocklist_blocklistsubmission_add')

    def test_delete_input(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        response = self.client.get(self.delete_url, follow=True)
        assert b'Add-on GUIDs (one per line)' in response.content

        # Submit an empty list of guids should redirect back to the page
        response = self.client.post(self.delete_url, {'guids': ''}, follow=False)
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'This field is required' in response.content

        # Any invalid guids should redirect back to the page too, with an error
        Block.objects.create(
            addon=addon_factory(guid='guid@'), updated_by=user_factory()
        )
        response = self.client.post(
            self.delete_url, {'guids': 'guid@\n{12345-6789}'}, follow=False
        )
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'Block with GUID {12345-6789} not found' in response.content

        # Valid blocks are redirected to the multiple guid view
        # We're purposely not creating the add-on here to test the edge-case
        # where the addon has been hard-deleted or otherwise doesn't exist.
        Block.objects.create(guid='{12345-6789}', updated_by=user_factory())
        assert Block.objects.count() == 2
        response = self.client.post(
            self.delete_url, {'guids': 'guid@\n{12345-6789}'}, follow=True
        )
        self.assertRedirects(response, self.submission_url, status_code=307)

        # If a block is already present in a submission though, we error
        BlocklistSubmission.objects.create(input_guids='guid@', min_version='1').save()
        response = self.client.post(
            self.delete_url, {'guids': 'guid@\n{12345-6789}'}, follow=False
        )
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'GUID guid@ is in a pending Submission' in response.content

    def _test_delete_multiple_submit(self, addon_adu):
        """addon_adu is important because whether dual signoff is needed is
        based on what the average_daily_users is."""
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        block_normal = Block.objects.create(
            addon=addon_factory(
                guid='guid@', name='Normal', average_daily_users=addon_adu
            ),
            updated_by=user_factory(),
        )
        block_no_addon = Block.objects.create(
            guid='{12345-6789}', updated_by=user_factory()
        )
        block_legacy = Block.objects.create(
            addon=addon_factory(guid='legacy@'),
            legacy_id='123456',
            updated_by=user_factory(),
        )

        response = self.client.post(
            self.submission_url,
            {
                'guids': 'guid@\n{12345-6789}\nlegacy@',
                'action': '1',
            },
            follow=True,
        )
        content = response.content.decode('utf-8')
        # meta data for block:
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'Delete Blocks' in content
        assert 'guid@' in content
        assert 'Normal' in content
        assert str(block_normal.addon.average_daily_users) in content
        assert '{12345-6789}' in content
        # The fields only used for Add/Change submissions shouldn't be shown
        assert '"min_version"' not in content
        assert '"max_version"' not in content
        assert 'reason' not in content
        assert 'legacy_id' not in content
        # Check we didn't delete the blocks already
        assert Block.objects.count() == 3
        assert BlocklistSubmission.objects.count() == 0

        # Create the block submission
        response = self.client.post(
            self.submission_url,
            {
                'input_guids': ('guid@\n{12345-6789}\nlegacy@'),
                'action': '1',
                '_save': 'Save',
            },
            follow=True,
        )
        assert response.status_code == 200
        return block_normal, block_no_addon, block_legacy

    def _test_delete_verify(
        self, block_with_addon, block_no_addon, block_legacy, has_signoff=True
    ):
        block_from_addon = block_with_addon.addon
        assert Block.objects.count() == 0
        assert BlocklistSubmission.objects.count() == 1
        submission = BlocklistSubmission.objects.get()

        add_log = ActivityLog.objects.for_addons(block_from_addon).last()
        assert add_log.action == amo.LOG.BLOCKLIST_BLOCK_DELETED.id
        assert add_log.arguments == [block_from_addon, block_from_addon.guid, None]
        if has_signoff:
            assert add_log.details['signoff_state'] == 'Approved'
            assert add_log.details['signoff_by'] == submission.signoff_by.id
        else:
            assert add_log.details['signoff_state'] == 'No Sign-off'
            assert 'signoff_by' not in add_log.details
        vlog = ActivityLog.objects.for_versions(block_from_addon.current_version).last()
        assert vlog == add_log

        assert submission.input_guids == ('guid@\n{12345-6789}\nlegacy@')

        assert submission.to_block == [
            {
                'guid': 'guid@',
                'id': block_with_addon.id,
                'average_daily_users': block_from_addon.average_daily_users,
            },
            {
                'guid': 'legacy@',
                'id': block_legacy.id,
                'average_daily_users': block_legacy.addon.average_daily_users,
            },
            {
                'guid': '{12345-6789}',
                'id': block_no_addon.id,
                'average_daily_users': -1,
            },
        ]
        assert not submission.block_set.all().exists()

    @override_switch('blocklist_legacy_submit', active=True)
    @mock.patch('olympia.blocklist.models.legacy_delete_blocks')
    def test_submit_no_dual_signoff(self, legacy_delete_blocks_mock):
        addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        (
            block_with_addon,
            block_no_addon,
            block_legacy,
        ) = self._test_delete_multiple_submit(addon_adu=addon_adu)
        self._test_delete_verify(
            block_with_addon, block_no_addon, block_legacy, has_signoff=False
        )
        legacy_delete_blocks_mock.assert_called_with(
            [block_with_addon, block_no_addon, block_legacy]
        )

    @override_switch('blocklist_legacy_submit', active=True)
    @mock.patch('olympia.blocklist.models.legacy_delete_blocks')
    def test_submit_dual_signoff(self, legacy_delete_blocks_mock):
        addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD + 1
        (
            block_with_addon,
            block_no_addon,
            block_legacy,
        ) = self._test_delete_multiple_submit(addon_adu=addon_adu)
        # Blocks shouldn't have been deleted yet
        assert Block.objects.count() == 3, Block.objects.all()

        submission = BlocklistSubmission.objects.get()
        submission.update(
            signoff_state=BlocklistSubmission.SIGNOFF_APPROVED,
            signoff_by=user_factory(),
        )
        assert submission.is_submission_ready
        submission.delete_block_objects()
        self._test_delete_verify(
            block_with_addon, block_no_addon, block_legacy, has_signoff=True
        )
        legacy_delete_blocks_mock.assert_called_with(
            [block_with_addon, block_no_addon, block_legacy]
        )

    def test_edit_with_delete_submission(self):
        threshold = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        block = Block.objects.create(
            addon=addon_factory(
                guid='guid@', name='Danger Danger', average_daily_users=threshold + 1
            ),
            updated_by=user_factory(),
        )
        mbs = BlocklistSubmission.objects.create(
            input_guids='guid@',
            updated_by=user_factory(),
            action=BlocklistSubmission.ACTION_DELETE,
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
        self.client.login(email=user.email)
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
        block = Block.objects.create(
            addon=addon_factory(guid='foo@baa', name='Danger Danger'),
            updated_by=user_factory(),
        )
        django_delete_url = reverse('admin:blocklist_block_delete', args=(block.pk,))

        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
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
        block = Block.objects.create(
            addon=addon_factory(guid='foo@baa', name='Danger Danger'),
            updated_by=user_factory(),
        )
        django_delete_url = reverse('admin:blocklist_block_delete', args=(block.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)
        assert Block.objects.count() == 1

        # Can't access delete confirmation page.
        response = self.client.get(django_delete_url, follow=True)
        assert response.status_code == 403
