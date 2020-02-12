import datetime
import json

from unittest import mock

from django.conf import settings
from django.contrib.admin.models import LogEntry, ADDITION
from django.contrib.contenttypes.models import ContentType

from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    TestCase, addon_factory, user_factory, version_factory)
from olympia.amo.urlresolvers import reverse

from ..models import Block, BlockSubmission


class TestBlockAdmin(TestCase):
    def setUp(self):
        self.admin_home_url = reverse('admin:index')
        self.list_url = reverse('admin:blocklist_block_changelist')
        self.add_url = reverse('admin:blocklist_block_add')
        self.submission_url = reverse('admin:blocklist_blocksubmission_add')

    def test_can_see_addon_module_in_admin_with_review_admin(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert modules == ['Blocklist']

    def test_can_not_see_addon_module_in_admin_without_permissions(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert modules == []

    def test_can_list(self):
        addon = addon_factory()
        Block.objects.create(guid=addon.guid, updated_by=user_factory())
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')

    def test_can_not_list_without_permission(self):
        addon = addon_factory()
        Block.objects.create(guid=addon.guid, updated_by=user_factory())
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 403
        assert addon.guid not in response.content.decode('utf-8')

    def test_add(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        response = self.client.get(self.add_url, follow=True)
        assert b'Add-on GUIDs (one per line)' in response.content

        # Submit an empty list of guids should redirect back to the page
        response = self.client.post(
            self.add_url, {'guids': ''}, follow=False)
        assert b'Add-on GUIDs (one per line)' in response.content

        # A single invalid guid should redirect back to the page too (for now)
        response = self.client.post(
            self.add_url, {'guids': 'guid@'}, follow=False)
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'Addon with GUID guid@ does not exist' in response.content

        # But should continue to the django admin add page if it exists
        addon = addon_factory(guid='guid@')
        response = self.client.post(
            self.add_url, {'guids': 'guid@'}, follow=True)
        self.assertRedirects(response, self.submission_url, status_code=307)

        # Multiple guids are redirected to the multiple guid view
        response = self.client.post(
            self.add_url, {'guids': 'guid@\nfoo@baa'}, follow=True)
        self.assertRedirects(response, self.submission_url, status_code=307)

        # An existing block will redirect to change view instead
        block = Block.objects.create(
            guid=addon.guid, updated_by=user_factory())
        response = self.client.post(
            self.add_url, {'guids': 'guid@'}, follow=True)
        self.assertRedirects(
            response,
            reverse('admin:blocklist_block_change', args=(block.pk,))
        )


class TestBlockSubmissionAdmin(TestCase):
    def setUp(self):
        self.submission_url = reverse('admin:blocklist_blocksubmission_add')
        self.multi_list_url = reverse(
            'admin:blocklist_blocksubmission_changelist')

    def test_add_single(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        addon = addon_factory(
            guid='guid@', name='Danger Danger', version_kw={'version': '1.2a'})
        first_version = addon.current_version
        second_version = version_factory(addon=addon, version='3')
        pending_version = version_factory(
            addon=addon, version='5.999',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        response = self.client.get(
            self.submission_url + '?guids=guid@', follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert str(addon.average_daily_users) in content
        assert Block.objects.count() == 0  # Check we didn't create it already
        assert 'Block History' in content
        assert 'changing this will force' not in content

        # Create the block
        response = self.client.post(
            self.submission_url, {
                'input_guids': 'guid@',
                'min_version': '0',
                'max_version': addon.current_version.version,
                'existing_min_version': '0',
                'existing_max_version': addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 200
        assert Block.objects.count() == 1
        block = Block.objects.first()
        assert block.addon == addon
        log = ActivityLog.objects.for_addons(addon).last()
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert log.arguments == [addon, addon.guid, block]
        assert log.details['min_version'] == '0'
        assert log.details['max_version'] == addon.current_version.version
        assert log.details['reason'] == 'some reason'
        block_log = ActivityLog.objects.for_block(block).filter(
            action=log.action).last()
        assert block_log == log
        block_log_by_guid = ActivityLog.objects.for_guidblock('guid@').filter(
            action=log.action).last()
        assert block_log_by_guid == log

        assert log == ActivityLog.objects.for_version(first_version).last()
        assert log == ActivityLog.objects.for_version(second_version).last()
        assert not ActivityLog.objects.for_version(pending_version).exists()

        response = self.client.get(
            reverse('admin:blocklist_block_change', args=(block.pk,)))
        content = response.content.decode('utf-8')
        todaysdate = datetime.datetime.now().date()
        assert f'<a href="dfd">{todaysdate}</a>' in content
        assert f'Block added by {user.name}: guid@' in content
        assert f'versions 0 - {addon.current_version.version}' in content
        assert f'Included in legacy blocklist' not in content

    def _test_add_multiple_submit(self, addon_adu):
        """addon_adu is important because whether dual signoff is needed is
        based on what the average_daily_users is."""
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        new_addon = addon_factory(
            guid='any@new', name='New Danger', average_daily_users=addon_adu)
        existing_and_full = Block.objects.create(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            min_version='0',
            max_version='*',
            include_in_legacy=True,
            updated_by=user_factory())
        partial_addon = addon_factory(
            guid='partial@existing', name='Partial Danger',
            average_daily_users=(addon_adu - 1))
        existing_and_partial = Block.objects.create(
            addon=partial_addon,
            min_version='1',
            max_version='99',
            include_in_legacy=True,
            updated_by=user_factory())
        response = self.client.post(
            self.submission_url,
            {'guids': 'any@new\npartial@existing\nfull@existing\ninvalid@'},
            follow=True)
        content = response.content.decode('utf-8')
        # meta data for new blocks and existing ones needing update:
        assert 'Add-on GUIDs (one per line)' not in content
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
        # we show the warning when the versions can affect existing blocks
        assert 'changing this will force' in content
        # Check we didn't create the block already
        assert Block.objects.count() == 2
        assert BlockSubmission.objects.count() == 0

        # Create the block submission
        response = self.client.post(
            self.submission_url, {
                'input_guids': (
                    'any@new\npartial@existing\nfull@existing\ninvalid@'),
                'min_version': '0',
                'max_version': '*',
                'existing_min_version': '0',
                'existing_max_version': '*',
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 200
        return (
            new_addon, existing_and_full, partial_addon, existing_and_partial)

    def _test_add_multiple_verify_blocks(self, new_addon, existing_and_full,
                                         partial_addon, existing_and_partial,
                                         has_signoff=True):
        assert Block.objects.count() == 3
        assert BlockSubmission.objects.count() == 1
        submission = BlockSubmission.objects.get()
        all_blocks = Block.objects.all()

        new_block = all_blocks[2]
        assert new_block.addon == new_addon
        add_log = ActivityLog.objects.for_addons(new_addon).last()
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
        block_log = ActivityLog.objects.for_block(new_block).filter(
            action=add_log.action).last()
        assert block_log == add_log
        vlog = ActivityLog.objects.for_version(
            new_addon.current_version).last()
        assert vlog == add_log

        existing_and_partial = existing_and_partial.reload()
        assert all_blocks[1] == existing_and_partial
        # confirm properties were updated
        assert existing_and_partial.min_version == '0'
        assert existing_and_partial.max_version == '*'
        assert existing_and_partial.reason == 'some reason'
        assert existing_and_partial.url == 'dfd'
        assert existing_and_partial.include_in_legacy is False
        edit_log = ActivityLog.objects.for_addons(partial_addon).last()
        assert edit_log.action == amo.LOG.BLOCKLIST_BLOCK_EDITED.id
        assert edit_log.arguments == [
            partial_addon, partial_addon.guid, existing_and_partial]
        assert edit_log.details['min_version'] == '0'
        assert edit_log.details['max_version'] == '*'
        assert edit_log.details['reason'] == 'some reason'
        if has_signoff:
            assert edit_log.details['signoff_state'] == 'Approved'
            assert edit_log.details['signoff_by'] == submission.signoff_by.id
        else:
            assert edit_log.details['signoff_state'] == 'No Sign-off'
            assert 'signoff_by' not in edit_log.details
        block_log = ActivityLog.objects.for_block(existing_and_partial).filter(
            action=edit_log.action).last()
        assert block_log == edit_log
        vlog = ActivityLog.objects.for_version(
            partial_addon.current_version).last()
        assert vlog == edit_log

        existing_and_full = existing_and_full.reload()
        assert all_blocks[0] == existing_and_full
        # confirm properties *were not* updated.
        assert existing_and_full.reason != 'some reason'
        assert existing_and_full.url != 'dfd'
        assert existing_and_full.include_in_legacy is True
        assert not ActivityLog.objects.for_addons(
            existing_and_full.addon).exists()
        assert not ActivityLog.objects.for_version(
            existing_and_full.addon.current_version).exists()

        assert submission.input_guids == (
            'any@new\npartial@existing\nfull@existing\ninvalid@')
        assert submission.min_version == new_block.min_version
        assert submission.max_version == new_block.max_version
        assert submission.url == new_block.url
        assert submission.reason == new_block.reason

        assert submission.to_block == [
            {'guid': 'any@new', 'id': 0,
             'average_daily_users': new_addon.average_daily_users},
            {'guid': 'partial@existing', 'id': existing_and_partial.id,
             'average_daily_users': partial_addon.average_daily_users}
        ]
        assert set(submission.block_set.all()) == {
            new_block, existing_and_partial}

    def test_submit_no_dual_signoff(self):
        addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        new_addon, existing_and_full, partial_addon, existing_and_partial = (
            self._test_add_multiple_submit(addon_adu=addon_adu))
        self._test_add_multiple_verify_blocks(
            new_addon, existing_and_full, partial_addon, existing_and_partial,
            has_signoff=False)

    def test_submit_dual_signoff(self):
        addon_adu = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD + 1
        new_addon, existing_and_full, partial_addon, existing_and_partial = (
            self._test_add_multiple_submit(addon_adu=addon_adu))
        # no new Block objects yet
        assert Block.objects.count() == 2
        # and existing block wasn't updated

        multi = BlockSubmission.objects.get()
        multi.update(
            signoff_state=BlockSubmission.SIGNOFF_APPROVED,
            signoff_by=user_factory())
        assert multi.is_save_to_blocks_permitted
        multi.save_to_blocks()
        self._test_add_multiple_verify_blocks(
            new_addon, existing_and_full, partial_addon, existing_and_partial)

    @override_switch('blocklist_admin_dualsignoff_disabled', active=True)
    def test_add_and_edit_with_different_min_max_versions(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        new_addon = addon_factory(
            guid='any@new', average_daily_users=100,
            version_kw={'version': '5.56'})
        existing_one_to_ten = Block.objects.create(
            addon=addon_factory(guid='partial@existing'),
            min_version='1',
            max_version='10',
            include_in_legacy=True,
            updated_by=user_factory())
        existing_zero_to_max = Block.objects.create(
            addon=addon_factory(
                guid='full@existing', average_daily_users=99,
                version_kw={'version': '10'}),
            min_version='0',
            max_version='*',
            include_in_legacy=True,
            updated_by=user_factory())
        response = self.client.post(
            self.submission_url,
            {'guids': 'any@new\npartial@existing\nfull@existing'},
            follow=True)

        # Check we've processed the guids correctly.
        doc = pq(response.content)
        assert 'full@existing' in doc('.field-existing-guids').text()
        assert 'partial@existing' in doc('.field-blocks-to-add').text()
        assert 'any@new' in doc('.field-blocks-to-add').text()

        # Check we didn't create the block already
        assert Block.objects.count() == 2
        assert BlockSubmission.objects.count() == 0

        # Change the min/max versions
        response = self.client.post(
            self.submission_url, {
                'input_guids': (
                    'any@new\npartial@existing\nfull@existing'),
                'min_version': '1',  # this is the field we can change
                'max_version': '10',  # this is the field we can change
                'existing_min_version': '0',  # this is a hidden field
                'existing_max_version': '*',  # this is a hidden field
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 200
        # No Block should have been changed or added
        assert Block.objects.count() == 2
        assert BlockSubmission.objects.count() == 0

        # The guids should have been processed differently now
        doc = pq(response.content)
        assert 'partial@existing' in doc('.field-existing-guids').text()
        assert 'full@existing' in doc('.field-blocks-to-add').text()
        assert 'any@new' in doc('.field-blocks-to-add').text()

        # We're submitting again, but now existing_min|max_version is the same
        response = self.client.post(
            self.submission_url, {
                'input_guids': (
                    'any@new\npartial@existing\nfull@existing'),
                'min_version': '1',  # this is the field we can change
                'max_version': '10',  # this is the field we can change
                'existing_min_version': '1',  # this is a hidden field
                'existing_max_version': '10',  # this is a hidden field
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)

        # This time the blocks are updated
        assert Block.objects.count() == 3
        assert BlockSubmission.objects.count() == 1
        all_blocks = Block.objects.all()

        new_block = all_blocks[2]
        assert new_block.addon == new_addon
        log = ActivityLog.objects.for_addons(new_addon).get()
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert log.arguments == [new_addon, new_addon.guid, new_block]
        assert log.details['min_version'] == '1'
        assert log.details['max_version'] == '10'
        assert log.details['reason'] == 'some reason'
        block_log = ActivityLog.objects.for_block(new_block).filter(
            action=log.action).last()
        assert block_log == log
        vlog = ActivityLog.objects.for_version(
            new_addon.current_version).last()
        assert vlog == log

        existing_zero_to_max = existing_zero_to_max.reload()
        assert all_blocks[1] == existing_zero_to_max
        # confirm properties were updated
        assert existing_zero_to_max.min_version == '1'
        assert existing_zero_to_max.max_version == '10'
        assert existing_zero_to_max.reason == 'some reason'
        assert existing_zero_to_max.url == 'dfd'
        assert existing_zero_to_max.include_in_legacy is False
        log = ActivityLog.objects.for_addons(existing_zero_to_max.addon).get()
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_EDITED.id
        assert log.arguments == [
            existing_zero_to_max.addon, existing_zero_to_max.guid,
            existing_zero_to_max]
        assert log.details['min_version'] == '1'
        assert log.details['max_version'] == '10'
        assert log.details['reason'] == 'some reason'
        block_log = ActivityLog.objects.for_block(existing_zero_to_max).filter(
            action=log.action).last()
        assert block_log == log
        vlog = ActivityLog.objects.for_version(
            existing_zero_to_max.addon.current_version).last()
        assert vlog == log

        existing_one_to_ten = existing_one_to_ten.reload()
        assert all_blocks[0] == existing_one_to_ten
        # confirm properties *were not* updated.
        assert existing_one_to_ten.reason != 'some reason'
        assert existing_one_to_ten.url != 'dfd'
        assert existing_one_to_ten.include_in_legacy is True
        assert not ActivityLog.objects.for_addons(
            existing_one_to_ten.addon).exists()
        assert not ActivityLog.objects.for_version(
            existing_one_to_ten.addon.current_version).exists()

        multi = BlockSubmission.objects.get()
        assert multi.input_guids == (
            'any@new\npartial@existing\nfull@existing')
        assert multi.min_version == new_block.min_version
        assert multi.max_version == new_block.max_version
        assert multi.url == new_block.url
        assert multi.reason == new_block.reason

        assert multi.to_block == [
            {'guid': 'any@new', 'id': 0,
             'average_daily_users': new_addon.average_daily_users},
            {'guid': 'full@existing', 'id': existing_zero_to_max.id,
             'average_daily_users':
             existing_zero_to_max.addon.average_daily_users}
        ]
        assert set(multi.block_set.all()) == {new_block, existing_zero_to_max}

    @mock.patch('olympia.blocklist.admin.GUID_FULL_LOAD_LIMIT', 1)
    def test_add_multiple_bulk_so_fake_block_objects(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        new_addon = addon_factory(guid='any@new', name='New Danger')
        Block.objects.create(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            min_version='0',
            max_version='*',
            include_in_legacy=True,
            updated_by=user_factory())
        partial_addon = addon_factory(
            guid='partial@existing', name='Partial Danger')
        Block.objects.create(
            addon=partial_addon,
            min_version='1',
            max_version='99',
            include_in_legacy=True,
            updated_by=user_factory())
        response = self.client.post(
            self.submission_url,
            {'guids': 'any@new\npartial@existing\nfull@existing\ninvalid@'},
            follow=True)
        content = response.content.decode('utf-8')
        # This metadata should exist
        assert new_addon.guid in content
        assert str(new_addon.average_daily_users) in content
        assert partial_addon.guid in content
        assert str(partial_addon.average_daily_users) in content
        assert 'full@existing' in content
        assert 'invalid@' in content

        # But Addon names or review links shouldn't have been loaded
        assert 'New Danger' not in content
        assert 'Partial Danger' not in content
        assert 'Full Danger' not in content
        assert 'Review Listed' not in content
        assert 'Review Unlisted' not in content

    def test_review_links(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        post_kwargs = {
            'path': self.submission_url,
            'data': {'guids': 'guid@\nfoo@baa\ninvalid@'},
            'follow': True}

        # An addon with only listed versions should have listed link
        addon = addon_factory(
            guid='guid@', name='Danger Danger', version_kw={'version': '0.1'})
        # This is irrelevant because a complete block doesn't have links
        Block.objects.create(
            addon=addon_factory(guid='foo@baa'),
            min_version="0",
            max_version="*",
            include_in_legacy=True,
            updated_by=user_factory())
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' not in response.content
        assert b'Edit Block' not in response.content
        assert not pq(response.content)('.existing_block')

        # Should work the same if partial block (exists but needs updating)
        existing_block = Block.objects.create(
            guid=addon.guid, min_version='8', updated_by=user_factory())
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' not in response.content
        assert pq(response.content)('.existing_block a').attr('href') == (
            reverse('admin:blocklist_block_change', args=(existing_block.pk,)))
        assert pq(response.content)('.existing_block').text() == (
            '[Edit Block: %s - %s]' % (existing_block.min_version, '*'))

        # And an unlisted version
        version_factory(
            addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED, version='0.2')
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' in response.content
        assert pq(response.content)('.existing_block a').attr('href') == (
            reverse('admin:blocklist_block_change', args=(existing_block.pk,)))
        assert pq(response.content)('.existing_block').text() == (
            '[Edit Block: %s - %s]' % (existing_block.min_version, '*'))

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
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        addon_factory(guid='any@new', name='New Danger')
        partial_addon = addon_factory(
            guid='partial@existing', name='Partial Danger')
        Block.objects.create(
            addon=partial_addon,
            min_version='1',
            max_version='99',
            include_in_legacy=True,
            updated_by=user_factory())
        response = self.client.post(
            self.submission_url, {
                'input_guids': 'any@new\npartial@existing\ninvalid@',
                'min_version': '5',
                'max_version': '3',
                'existing_min_version': '5',
                'existing_max_version': '3',
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 200
        assert b'Min version can not be greater than Max' in response.content
        assert Block.objects.count() == 1

    def test_can_not_add_without_create_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        # The signoff permission shouldn't be sufficient
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.login(email=user.email)

        addon_factory(guid='guid@', name='Danger Danger')
        existing = Block.objects.create(
            addon=addon_factory(guid='foo@baa'),
            min_version="1",
            max_version="99",
            include_in_legacy=True,
            updated_by=user_factory())
        response = self.client.post(
            self.submission_url,
            {'guids': 'guid@\nfoo@baa\ninvalid@'},
            follow=True)
        assert response.status_code == 403
        assert b'Danger Danger' not in response.content

        # Try to create the block anyway
        response = self.client.post(
            self.submission_url, {
                'input_guids': 'guid@\nfoo@baa\ninvalid@',
                'min_version': '0',
                'max_version': '*',
                'existing_min_version': '0',
                'existing_max_version': '*',
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 403
        assert Block.objects.count() == 1
        existing = existing.reload()
        assert existing.min_version == '1'  # check the values didn't update.

    def _test_can_list_with_permission(self, permission):
        mbs = BlockSubmission.objects.create(
            updated_by=user_factory(display_name='Bób'))
        # add some guids to the multi block to test out the counts in the list
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs.update(input_guids='guid@\ninvalid@\nsecond@invalid')
        mbs.save()
        assert mbs.to_block == [
            {'guid': 'guid@',
             'id': 0,
             'average_daily_users': addon.average_daily_users}]

        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, permission)
        self.client.login(email=user.email)

        response = self.client.get(self.multi_list_url, follow=True)
        assert response.status_code == 200
        assert 'Bób' in response.content.decode('utf-8')
        doc = pq(response.content)
        assert doc('th.field-blocks_count').text() == '1 add-ons'
        assert doc('.field-signoff_state').text() == 'Pending'

    def test_can_list_with_blocklist_create(self):
        self._test_can_list_with_permission('Blocklist:Create')

    def test_can_list_with_blocklist_signoff(self):
        self._test_can_list_with_permission('Blocklist:Signoff')

    def test_can_not_list_without_permission(self):
        BlockSubmission.objects.create(
            updated_by=user_factory(display_name='Bób'))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)

        response = self.client.get(self.multi_list_url, follow=True)
        assert response.status_code == 403
        assert 'Bób' not in response.content.decode('utf-8')

    def test_signoff_page(self):
        threshold = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
        addon = addon_factory(
            guid='guid@', name='Danger Danger',
            average_daily_users=threshold + 1)
        mbs = BlockSubmission.objects.create(
            input_guids='guid@\ninvalid@\nsecond@invalid',
            updated_by=user_factory())
        assert mbs.to_block == [
            {'guid': 'guid@',
             'id': 0,
             'average_daily_users': addon.average_daily_users}]

        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        multi_url = reverse(
            'admin:blocklist_blocksubmission_change', args=(mbs.id,))

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
            multi_url, {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'min_version': '1',  # should be ignored
                'max_version': '99',  # should be ignored
                'url': 'new.url',
                'reason': 'a reason',
                '_save': 'Update',
            },
            follow=True)
        assert response.status_code == 200
        mbs = mbs.reload()

        # the read-only values above weren't changed.
        assert mbs.input_guids == 'guid@\ninvalid@\nsecond@invalid'
        assert mbs.min_version == '0'
        assert mbs.max_version == '*'
        # but the other details were
        assert mbs.url == 'new.url'
        assert mbs.reason == 'a reason'

        # The blocksubmission wasn't approved or rejected though
        assert mbs.signoff_state == BlockSubmission.SIGNOFF_PENDING
        assert Block.objects.count() == 0

        log_entry = LogEntry.objects.get()
        assert log_entry.user == user
        assert log_entry.object_id == str(mbs.id)
        assert log_entry.change_message == json.dumps(
            [{'changed': {'fields': ['url', 'reason']}}])

        response = self.client.get(multi_url, follow=True)
        assert (
            b'Changed &quot;Pending: guid@, ...; new.url; a reason' in
            response.content)

    def test_edit_page_with_blocklist_signoff(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlockSubmission.objects.create(
            input_guids='guid@\ninvalid@\nsecond@invalid',
            updated_by=user_factory())
        assert mbs.to_block == [
            {'guid': 'guid@',
             'id': 0,
             'average_daily_users': addon.average_daily_users}]

        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.login(email=user.email)
        multi_url = reverse(
            'admin:blocklist_blocksubmission_change', args=(mbs.id,))

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
            multi_url, {
                'input_guids': 'guid2@\nfoo@baa',
                'min_version': '1',
                'max_version': '99',
                'url': 'new.url',
                'reason': 'a reason',
                '_save': 'Update',
            },
            follow=True)
        assert response.status_code == 403
        mbs = mbs.reload()

        # none of the values above were changed because they're all read-only.
        assert mbs.input_guids == 'guid@\ninvalid@\nsecond@invalid'
        assert mbs.min_version == '0'
        assert mbs.max_version == '*'
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

        # The blocksubmission wasn't approved or rejected either
        assert mbs.signoff_state == BlockSubmission.SIGNOFF_PENDING
        assert Block.objects.count() == 0
        assert LogEntry.objects.count() == 0

    def test_signoff_approve(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlockSubmission.objects.create(
            input_guids='guid@\ninvalid@',
            updated_by=user_factory())
        assert mbs.to_block == [
            {'guid': 'guid@',
             'id': 0,
             'average_daily_users': addon.average_daily_users}]

        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.login(email=user.email)
        multi_url = reverse(
            'admin:blocklist_blocksubmission_change', args=(mbs.id,))
        response = self.client.post(
            multi_url, {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'min_version': '1',  # should be ignored
                'max_version': '99',  # should be ignored
                'url': 'new.url',  # should be ignored
                'reason': 'a reason',  # should be ignored
                '_signoff': 'Approve Submission',
            },
            follow=True)
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
        add_log = logs[1]
        signoff_log = logs[0]
        assert add_log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert add_log.arguments == [addon, addon.guid, new_block]
        assert add_log.details['min_version'] == '0'
        assert add_log.details['max_version'] == '*'
        assert add_log.details['reason'] == ''
        assert add_log.details['signoff_state'] == 'Approved'
        assert add_log.details['signoff_by'] == user.id
        block_log = ActivityLog.objects.for_block(new_block).filter(
            action=add_log.action).last()
        assert block_log == add_log
        vlog = ActivityLog.objects.for_version(addon.current_version).last()
        assert vlog == add_log

        assert signoff_log.action == amo.LOG.BLOCKLIST_SIGNOFF.id
        assert signoff_log.arguments == [addon, addon.guid, 'add', new_block]
        assert signoff_log.user == user

        assert mbs.to_block == [
            {'guid': 'guid@',
             'id': 0,
             'average_daily_users': addon.average_daily_users}]
        assert list(mbs.block_set.all()) == [new_block]

        log_entry = LogEntry.objects.last()
        assert log_entry.user == user
        assert log_entry.object_id == str(mbs.id)
        other_obj = addon_factory(id=mbs.id)
        LogEntry.objects.log_action(
            user_factory().id, ContentType.objects.get_for_model(other_obj).pk,
            other_obj.id, repr(other_obj), ADDITION, 'not a Block!')

        response = self.client.get(multi_url, follow=True)
        assert (
            b'Changed &quot;Approved: guid@, ...; ; '
            b'&quot; - Sign-off Approval' in
            response.content)
        assert b'not a Block!' not in response.content

    def test_signoff_reject(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlockSubmission.objects.create(
            input_guids='guid@\ninvalid@',
            updated_by=user_factory())
        assert mbs.to_block == [
            {'guid': 'guid@',
             'id': 0,
             'average_daily_users': addon.average_daily_users}]

        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Signoff')
        self.client.login(email=user.email)
        multi_url = reverse(
            'admin:blocklist_blocksubmission_change', args=(mbs.id,))
        response = self.client.post(
            multi_url, {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'min_version': '1',  # should be ignored
                'max_version': '99',  # should be ignored
                'url': 'new.url',  # should be ignored
                'reason': 'a reason',  # should be ignored
                '_reject': 'Reject Submission',
            },
            follow=True)
        assert response.status_code == 200
        mbs = mbs.reload()

        # the read-only values above weren't changed.
        assert mbs.input_guids == 'guid@\ninvalid@'
        assert mbs.min_version == '0'
        assert mbs.max_version == '*'
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

        # And the blocksubmission was rejected, so no Blocks created
        assert mbs.signoff_state == BlockSubmission.SIGNOFF_REJECTED
        assert Block.objects.count() == 0
        assert not mbs.is_save_to_blocks_permitted

        log_entry = LogEntry.objects.last()
        assert log_entry.user == user
        assert log_entry.object_id == str(mbs.id)
        other_obj = addon_factory(id=mbs.id)
        LogEntry.objects.log_action(
            user_factory().id, ContentType.objects.get_for_model(other_obj).pk,
            other_obj.id, repr(other_obj), ADDITION, 'not a Block!')

        response = self.client.get(multi_url, follow=True)
        assert (
            b'Changed &quot;Rejected: guid@, ...; ; '
            b'&quot; - Sign-off Rejection' in
            response.content)
        assert b'not a Block!' not in response.content

    def test_cannot_approve_with_only_block_create_permission(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlockSubmission.objects.create(
            input_guids='guid@\ninvalid@',
            updated_by=user_factory())
        assert mbs.to_block == [
            {'guid': 'guid@',
             'id': 0,
             'average_daily_users': addon.average_daily_users}]

        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        multi_url = reverse(
            'admin:blocklist_blocksubmission_change', args=(mbs.id,))
        response = self.client.post(
            multi_url, {
                'input_guids': 'guid2@\nfoo@baa',  # should be ignored
                'min_version': '1',  # should be ignored
                'max_version': '99',  # should be ignored
                'url': 'new.url',  # could be updated with this permission
                'reason': 'a reason',  # could be updated with this permission
                '_signoff': 'Approve Submission',
            },
            follow=True)
        assert response.status_code == 403
        mbs = mbs.reload()
        # It wasn't signed off
        assert not mbs.signoff_by
        assert mbs.signoff_state == BlockSubmission.SIGNOFF_PENDING
        # And the details weren't updated either
        assert mbs.url != 'new.url'
        assert mbs.reason != 'a reason'

    def test_cannot_reject_with_only_block_create_permission(self):
        pass

    def test_signed_off_view(self):
        addon = addon_factory(guid='guid@', name='Danger Danger')
        mbs = BlockSubmission.objects.create(
            input_guids='guid@\ninvalid@\nsecond@invalid',
            updated_by=user_factory(),
            signoff_by=user_factory(),
            signoff_state=BlockSubmission.SIGNOFF_APPROVED)
        assert mbs.to_block == [
            {'guid': 'guid@',
             'id': 0,
             'average_daily_users': addon.average_daily_users}]
        mbs.save_to_blocks()
        block = Block.objects.get()

        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        multi_view_url = reverse(
            'admin:blocklist_blocksubmission_change', args=(mbs.id,))

        response = self.client.get(multi_view_url, follow=True)
        assert response.status_code == 200
        assert b'guid@<br>invalid@<br>second@invalid' in response.content
        doc = pq(response.content)
        review_link = doc('div.field-blocks div div a')[0]
        assert review_link.attrib['href'] == absolutify(reverse(
            'reviewers.review', args=(addon.pk,)))
        guid_link = doc('div.field-blocks div div a')[1]
        assert guid_link.attrib['href'] == reverse(
            'admin:blocklist_block_change', args=(block.pk,))
        assert not doc('submit-row input')


class TestBlockAdminEdit(TestCase):
    def setUp(self):
        self.addon = addon_factory(guid='guid@', name='Danger Danger')
        self.block = Block.objects.create(
            guid=self.addon.guid, updated_by=user_factory())
        self.change_url = reverse(
            'admin:blocklist_block_change', args=(self.block.pk,))
        self.submission_url = reverse('admin:blocklist_blocksubmission_add')

    def test_edit(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert str(self.addon.average_daily_users) in content
        assert 'Block History' in content

        # Change the block
        response = self.client.post(
            self.change_url, {
                'addon_id': addon_factory().id,  # new addon should be ignored
                'input_guids': self.block.guid,
                'min_version': '0',
                'max_version': self.addon.current_version.version,
                'url': 'https://foo.baa',
                'reason': 'some other reason',
                'include_in_legacy': True,
                '_continue': 'Save and continue editing',
            },
            follow=True)
        assert response.status_code == 200
        assert Block.objects.count() == 1  # check we didn't create another
        assert Block.objects.first().addon == self.addon  # wasn't changed
        log = ActivityLog.objects.for_addons(self.addon).last()
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_EDITED.id
        assert log.arguments == [self.addon, self.addon.guid, self.block]
        assert log.details['min_version'] == '0'
        assert log.details['max_version'] == self.addon.current_version.version
        assert log.details['reason'] == 'some other reason'
        block_log = ActivityLog.objects.for_block(self.block).filter(
            action=log.action).last()
        assert block_log == log
        block_log_by_guid = ActivityLog.objects.for_guidblock('guid@').filter(
            action=log.action).last()
        assert block_log_by_guid == log
        vlog = ActivityLog.objects.for_version(
            self.addon.current_version).last()
        assert vlog == log

        # Check the block history contains the edit just made.
        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        todaysdate = datetime.datetime.now().date()
        assert f'<a href="https://foo.baa">{todaysdate}</a>' in content
        assert f'Block edited by {user.name}: {self.block.guid}' in content
        assert f'versions 0 - {self.addon.current_version.version}' in content
        assert f'Included in legacy blocklist' in content

    def test_invalid_versions_not_accepted(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        self.addon.current_version.update(version='123.4b5')
        version_factory(addon=self.addon, version='678')
        # Update min_version in self.block to a version that doesn't exist
        self.block.update(min_version='444.4a')

        response = self.client.get(self.change_url, follow=True)
        content = response.content.decode('utf-8')
        doc = pq(content)
        ver_list = doc('#id_min_version option')
        assert len(ver_list) == 4
        assert ver_list.eq(0).attr['value'] == '444.4a'
        assert ver_list.eq(0).text() == '(invalid)'
        assert ver_list.eq(1).attr['value'] == '0'
        assert ver_list.eq(2).attr['value'] == '123.4b5'
        assert ver_list.eq(3).attr['value'] == '678'
        ver_list = doc('#id_max_version option')
        assert len(ver_list) == 3
        assert ver_list.eq(0).attr['value'] == '*'
        assert ver_list.eq(1).attr['value'] == '123.4b5'
        assert ver_list.eq(2).attr['value'] == '678'

        data = {
            'input_guids': self.block.guid,
            'url': 'https://foo.baa',
            'reason': 'some other reason',
            'include_in_legacy': True,
            '_save': 'Update',
        }
        # Try saving the form with the same min_version
        response = self.client.post(
            self.change_url, dict(
                min_version='444.4a',  # current value, but not a version.
                max_version=self.addon.current_version.version,  # valid
                **data),
            follow=True)
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
            self.change_url, dict(
                min_version='123.4b5',
                max_version='*',
                **data),
            follow=True)
        assert response.status_code == 200
        assert b'Invalid version' not in response.content
        self.block = self.block.reload()
        assert self.block.min_version == '123.4b5'  # changed
        assert self.block.max_version == '*'
        assert ActivityLog.objects.for_addons(self.addon).exists()
        # the value shouldn't be in the list of versions either any longer.
        assert b'444.4a' not in response.content

    def test_can_not_edit_without_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)

        response = self.client.get(self.change_url, follow=True)
        assert response.status_code == 403
        assert b'Danger Danger' not in response.content

        # Try to edit the block anyway
        response = self.client.post(
            self.change_url, {
                'min_version': '0',
                'max_version': self.addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 403
        assert Block.objects.count() == 1


class TestBlockAdminDelete(TestCase):
    def setUp(self):
        self.addon = addon_factory(guid='guid@', name='Danger Danger')
        self.block = Block.objects.create(
            guid=self.addon.guid, updated_by=user_factory())
        self.delete_url = reverse(
            'admin:blocklist_block_delete', args=(self.block.pk,))
        self.submission_url = reverse('admin:blocklist_blocksubmission_add')

    def test_can_delete(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)
        assert Block.objects.count() == 1
        guid = self.block.guid

        # Can access delete confirmation page.
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 200
        assert Block.objects.count() == 1

        # Can actually delete.
        response = self.client.post(
            self.delete_url,
            {'post': 'yes'},
            follow=True)
        assert response.status_code == 200
        assert Block.objects.count() == 0

        log = ActivityLog.objects.for_addons(self.addon).last()
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_DELETED.id
        assert log.arguments == [self.addon, self.addon.guid, None]

        # The BlockLog is still there too so it can be referenced by guid
        blocklog = ActivityLog.objects.for_guidblock(guid).first()
        assert log == blocklog
        vlog = ActivityLog.objects.for_version(
            self.addon.current_version).last()
        assert vlog == log

        # And if we try to add the guid again the old history is there
        response = self.client.get(
            self.submission_url, {'guids': 'guid@'}, follow=True)
        content = response.content.decode('utf-8')
        assert f'Block deleted by {user.name}: guid@.' in content

    def test_can_not_delete_without_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        assert Block.objects.count() == 1

        # Can't access delete confirmation page.
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403

        # Can't actually delete either.
        response = self.client.post(
            self.delete_url,
            {'post': 'yes'},
            follow=True)
        assert response.status_code == 403
        assert Block.objects.count() == 1

        assert not ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.BLOCKLIST_BLOCK_DELETED.id).exists()
        assert not ActivityLog.objects.for_block(self.block).filter(
            action=amo.LOG.BLOCKLIST_BLOCK_DELETED.id).exists()


class TestBlockAdminBulkDelete(TestCase):
    def setUp(self):
        self.delete_url = reverse('admin:blocklist_block_delete_multiple')

    def test_input(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Blocklist:Create')
        self.client.login(email=user.email)

        response = self.client.get(self.delete_url, follow=True)
        assert b'Add-on GUIDs (one per line)' in response.content

        # Submit an empty list of guids should redirect back to the page
        response = self.client.post(
            self.delete_url, {'guids': ''}, follow=False)
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'This field is required' in response.content

        # Any invalid guids should redirect back to the page too, with an error
        block_with_addon = Block.objects.create(
            addon=addon_factory(guid='guid@'), updated_by=user_factory())
        response = self.client.post(
            self.delete_url, {'guids': 'guid@\n{12345-6789}'}, follow=False)
        assert b'Add-on GUIDs (one per line)' in response.content
        assert b'Block with GUID {12345-6789} not found' in response.content

        # We're purposely not creating the add-on here to test the edge-case
        # where the addon has been hard-deleted or otherwise doesn't exist.
        block_no_addon = Block.objects.create(
            guid='{12345-6789}', updated_by=user_factory())
        assert Block.objects.count() == 2
        # But should continue to django's deleted_selected if they all exist
        response = self.client.post(
            self.delete_url, {'guids': 'guid@\n{12345-6789}'}, follow=True)
        assert b'Add-on GUIDs (one per line)' not in response.content
        assert b'Are you sure?' in response.content

        # The delete selected form is different but submits to the current url,
        # so we have to redirect to the changelist page to takeover and
        # actually delete.
        data = {
            'action': 'delete_selected',
            'post': 'yes',
            '_selected_action': (
                str(block_with_addon.id), str(block_no_addon.id)),
        }
        response = self.client.post(self.delete_url, data, follow=True)
        self.assertRedirects(
            response,
            reverse('admin:blocklist_block_changelist'), status_code=307)
        assert Block.objects.count() == 0
