import datetime

from unittest import mock

from pyquery import PyQuery as pq

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import (
    TestCase, addon_factory, user_factory, version_factory)
from olympia.amo.urlresolvers import reverse

from ..models import Block, MultiBlockSubmit


class TestBlockAdminList(TestCase):
    def setUp(self):
        self.admin_home_url = reverse('admin:index')
        self.list_url = reverse('admin:blocklist_block_changelist')

    def test_can_see_addon_module_in_admin_with_review_admin(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
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
        Block.objects.create(guid=addon.guid)
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')

    def test_can_not_list_without_permission(self):
        addon = addon_factory()
        Block.objects.create(guid=addon.guid)
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 403
        assert addon.guid not in response.content.decode('utf-8')


class TestBlockAdminAdd(TestCase):
    def setUp(self):
        self.add_url = reverse('admin:blocklist_block_add')
        self.single_url = reverse('admin:blocklist_block_add_single')
        self.multi_url = reverse('admin:blocklist_multiblocksubmit_add')

    def test_add(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
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
        assert b'Addon with specified GUID does not exist' in response.content

        # But should continue to the django admin add page if it exists
        addon = addon_factory(guid='guid@')
        response = self.client.post(
            self.add_url, {'guids': 'guid@'}, follow=True)
        self.assertRedirects(response, self.single_url + '?guid=guid@')

        # Multiple guids are redirected to the multiple guid view
        response = self.client.post(
            self.add_url, {'guids': 'guid@\nfoo@baa'}, follow=True)
        self.assertRedirects(response, self.multi_url, status_code=307)

        # An existing block will redirect to change view instead
        block = Block.objects.create(guid=addon.guid)
        response = self.client.post(
            self.add_url, {'guids': 'guid@'}, follow=True)
        self.assertRedirects(
            response,
            reverse('admin:blocklist_block_change', args=(block.pk,))
        )

    def test_add_single(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
        self.client.login(email=user.email)

        addon = addon_factory(
            guid='guid@', name='Danger Danger', version_kw={'version': '1.2a'})
        first_version = addon.current_version
        second_version = version_factory(addon=addon, version='3')
        pending_version = version_factory(
            addon=addon, version='5.999',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        response = self.client.get(
            self.single_url + '?guid=guid@', follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert str(addon.average_daily_users) in content
        assert Block.objects.count() == 0  # Check we didn't create it already
        assert 'Block History' in content

        # Create the block
        response = self.client.post(
            self.single_url + '?guid=guid@', {
                'min_version': '0',
                'max_version': addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                '_continue': 'Save',
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

        content = response.content.decode('utf-8')
        todaysdate = datetime.datetime.now().date()
        assert f'<a href="dfd">{todaysdate}</a>' in content
        assert f'Block added by {user.name}: guid@' in content
        assert f'versions 0 - {addon.current_version.version}' in content
        assert f'Included in legacy blocklist' not in content

    def test_review_links(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
        self.client.login(email=user.email)

        addon = addon_factory(guid='guid@', name='Danger Danger')
        response = self.client.get(
            self.single_url + '?guid=guid@', follow=True)
        content = response.content.decode('utf-8')
        assert 'Review Listed' in content
        assert 'Review Unlisted' not in content  # Theres only a listed version

        version_factory(addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(
            self.single_url + '?guid=guid@', follow=True)
        content = response.content.decode('utf-8')
        assert 'Review Listed' in content
        assert 'Review Unlisted' in content, content

        addon.current_version.delete(hard=True)
        response = self.client.get(
            self.single_url + '?guid=guid@', follow=True)
        content = response.content.decode('utf-8')
        assert 'Review Listed' not in content
        assert 'Review Unlisted' in content

    def test_can_not_set_min_version_above_max_version(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
        self.client.login(email=user.email)

        addon = addon_factory(
            guid='guid@', name='Danger Danger', version_kw={'version': '3'})
        version_factory(addon=addon, version='5')

        response = self.client.post(
            self.single_url + '?guid=guid@', {
                'min_version': '5',
                'max_version': '3',
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 200
        assert b'Min version can not be greater than Max' in response.content
        assert Block.objects.count() == 0

        response = self.client.post(
            self.single_url + '?guid=guid@', {
                'min_version': '3',
                'max_version': '5',
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 200
        assert Block.objects.count() == 1

    def test_can_not_add_without_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)

        addon = addon_factory(guid='guid@', name='Danger Danger')
        response = self.client.get(
            self.single_url + '?guid=guid@', follow=True)
        assert response.status_code == 403
        assert b'Danger Danger' not in response.content

        # Try to create the block anyway
        response = self.client.post(
            self.single_url + '?guid=guid@', {
                'min_version': '0',
                'max_version': addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 403
        assert Block.objects.count() == 0


class TestMultiBlockSubmitAdmin(TestCase):
    def setUp(self):
        self.multi_url = reverse('admin:blocklist_multiblocksubmit_add')
        self.multi_list_url = reverse(
            'admin:blocklist_multiblocksubmit_changelist')

    def test_add_multiple(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
        self.client.login(email=user.email)

        new_addon = addon_factory(
            guid='any@new', name='New Danger', average_daily_users=100)
        existing_and_full = Block.objects.create(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            min_version='0',
            max_version='*',
            include_in_legacy=True)
        partial_addon = addon_factory(
            guid='partial@existing', name='Partial Danger',
            average_daily_users=99)
        existing_and_partial = Block.objects.create(
            addon=partial_addon,
            min_version='1',
            max_version='99',
            include_in_legacy=True)
        response = self.client.post(
            self.multi_url,
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
        # Check we didn't create the block already
        assert Block.objects.count() == 2
        assert MultiBlockSubmit.objects.count() == 0

        # Create the block
        response = self.client.post(
            self.multi_url, {
                'input_guids': (
                    'any@new\npartial@existing\nfull@existing\ninvalid@'),
                'min_version': '0',
                'max_version': '*',
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 200
        assert Block.objects.count() == 3
        assert MultiBlockSubmit.objects.count() == 1
        all_blocks = Block.objects.all()

        new_block = all_blocks[2]
        assert new_block.addon == new_addon
        log = ActivityLog.objects.for_addons(new_addon).get()
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert log.arguments == [new_addon, new_addon.guid, new_block]
        assert log.details['min_version'] == '0'
        assert log.details['max_version'] == '*'
        assert log.details['reason'] == 'some reason'
        block_log = ActivityLog.objects.for_block(new_block).filter(
            action=log.action).last()
        assert block_log == log
        vlog = ActivityLog.objects.for_version(
            new_addon.current_version).last()
        assert vlog == log

        existing_and_partial = existing_and_partial.reload()
        assert all_blocks[1] == existing_and_partial
        # confirm properties were updated
        assert existing_and_partial.min_version == '0'
        assert existing_and_partial.max_version == '*'
        assert existing_and_partial.reason == 'some reason'
        assert existing_and_partial.url == 'dfd'
        assert existing_and_partial.include_in_legacy is False
        log = ActivityLog.objects.for_addons(partial_addon).get()
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_EDITED.id
        assert log.arguments == [
            partial_addon, partial_addon.guid, existing_and_partial]
        assert log.details['min_version'] == '0'
        assert log.details['max_version'] == '*'
        assert log.details['reason'] == 'some reason'
        block_log = ActivityLog.objects.for_block(existing_and_partial).filter(
            action=log.action).last()
        assert block_log == log
        vlog = ActivityLog.objects.for_version(
            partial_addon.current_version).last()
        assert vlog == log

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

        multi = MultiBlockSubmit.objects.get()
        assert multi.input_guids == (
            'any@new\npartial@existing\nfull@existing\ninvalid@')
        assert multi.min_version == new_block.min_version
        assert multi.max_version == new_block.max_version
        assert multi.url == new_block.url
        assert multi.reason == new_block.reason

        assert multi.processed_guids == {
            'invalid_guids': ['invalid@'],
            'existing_guids': ['full@existing'],
            'blocks': ['any@new', 'partial@existing'],
            'blocks_saved': [
                [new_block.id, 'any@new'],
                [existing_and_partial.id, 'partial@existing']],
        }

    @mock.patch('olympia.blocklist.admin.GUID_FULL_LOAD_LIMIT', 1)
    def test_add_multiple_bulk_so_fake_block_objects(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
        self.client.login(email=user.email)

        new_addon = addon_factory(guid='any@new', name='New Danger')
        Block.objects.create(
            addon=addon_factory(guid='full@existing', name='Full Danger'),
            min_version='0',
            max_version='*',
            include_in_legacy=True)
        partial_addon = addon_factory(
            guid='partial@existing', name='Partial Danger')
        Block.objects.create(
            addon=partial_addon,
            min_version='1',
            max_version='99',
            include_in_legacy=True)
        response = self.client.post(
            self.multi_url,
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
        self.grant_permission(user, 'Reviews:Admin')
        self.client.login(email=user.email)
        post_kwargs = {
            'path': self.multi_url,
            'data': {'guids': 'guid@\nfoo@baa\ninvalid@'},
            'follow': True}

        # An addon with only listed versions should have listed link
        addon = addon_factory(guid='guid@', name='Danger Danger')
        # This is irrelevant because a complete block doesn't have links
        Block.objects.create(
            addon=addon_factory(guid='foo@baa'),
            min_version="0",
            max_version="*",
            include_in_legacy=True)
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' not in response.content
        assert b'edit existing Block' not in response.content

        # Should work the same if partial block (exists but needs updating)
        existing_block = Block.objects.create(guid=addon.guid, min_version='8')
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' not in response.content
        assert b'edit existing Block' in response.content

        # And an unlisted version
        version_factory(addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' in response.content
        assert b'edit existing Block' in response.content

        # And delete the block again
        existing_block.delete()
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' in response.content
        assert b'Review Unlisted' in response.content
        assert b'edit existing Block' not in response.content

        addon.current_version.delete(hard=True)
        response = self.client.post(**post_kwargs)
        assert b'Review Listed' not in response.content
        assert b'Review Unlisted' in response.content

    def test_can_not_add_without_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)

        addon_factory(guid='guid@', name='Danger Danger')
        existing = Block.objects.create(
            addon=addon_factory(guid='foo@baa'),
            min_version="1",
            max_version="99",
            include_in_legacy=True)
        response = self.client.post(
            self.multi_url,
            {'guids': 'guid@\nfoo@baa\ninvalid@'},
            follow=True)
        assert response.status_code == 403
        assert b'Danger Danger' not in response.content

        # Try to create the block anyway
        response = self.client.post(
            self.multi_url, {
                'input_guids': 'guid@\nfoo@baa\ninvalid@',
                'min_version': '0',
                'max_version': '*',
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 403
        assert Block.objects.count() == 1
        existing = existing.reload()
        assert existing.min_version == '1'  # check the values didn't update.

    def test_can_list(self):
        mbs = MultiBlockSubmit.objects.create(
            updated_by=user_factory(display_name='Bób'))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
        self.client.login(email=user.email)
        response = self.client.get(self.multi_list_url, follow=True)
        assert response.status_code == 200
        assert 'Bób' in response.content.decode('utf-8')

        # add some guids to the multi block to test out the counts in the list
        addon_factory(guid='guid@', name='Danger Danger')
        mbs.update(input_guids='guid@\ninvalid@\nsecond@invalid')
        mbs.save()
        assert mbs.processed_guids['existing_guids'] == []
        # the order of invalid_guids is indeterminate.
        assert set(mbs.processed_guids['invalid_guids']) == {
            'invalid@', 'second@invalid'}
        assert len(mbs.processed_guids['invalid_guids']) == 2
        assert mbs.processed_guids['blocks'] == ['guid@']
        response = self.client.get(self.multi_list_url, follow=True)
        doc = pq(response.content)
        assert doc('td.field-invalid_guid_count').text() == '2'
        assert doc('td.field-existing_guid_count').text() == '0'
        assert doc('td.field-blocks_count').text() == '1'
        assert doc('td.field-blocks_submitted_count').text() == '0'

    def test_can_not_list_without_permission(self):
        MultiBlockSubmit.objects.create(
            updated_by=user_factory(display_name='Bób'))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.multi_list_url, follow=True)
        assert response.status_code == 403
        assert 'Bób' not in response.content.decode('utf-8')

    def test_view(self):
        addon_factory(guid='guid@', name='Danger Danger')
        mbs = MultiBlockSubmit.objects.create(
            input_guids='guid@\ninvalid@\nsecond@invalid')
        assert mbs.processed_guids['existing_guids'] == []
        # the order of invalid_guids is indeterminate.
        assert set(mbs.processed_guids['invalid_guids']) == {
            'invalid@', 'second@invalid'}
        assert len(mbs.processed_guids['invalid_guids']) == 2
        assert mbs.processed_guids['blocks'] == ['guid@']
        mbs.save_to_blocks()
        block = Block.objects.get()

        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
        self.client.login(email=user.email)
        multi_view_url = reverse(
            'admin:blocklist_multiblocksubmit_change', args=(mbs.id,))

        response = self.client.get(multi_view_url, follow=True)
        assert response.status_code == 200

        assert b'guid@<br>invalid@<br>second@invalid' in response.content

        doc = pq(response.content)
        guid_link = doc('div.field-blocks_submitted div div a')
        assert guid_link.attr('href') == reverse(
            'admin:blocklist_block_change', args=(block.pk,))
        assert guid_link.text() == 'guid@'


class TestBlockAdminEdit(TestCase):
    def setUp(self):
        self.addon = addon_factory(guid='guid@', name='Danger Danger')
        self.block = Block.objects.create(guid=self.addon.guid)
        self.change_url = reverse(
            'admin:blocklist_block_change', args=(self.block.pk,))
        self.delete_url = reverse(
            'admin:blocklist_block_delete', args=(self.block.pk,))
        self.single_url = reverse('admin:blocklist_block_add_single')

    def test_edit(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
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
        content = response.content.decode('utf-8')
        todaysdate = datetime.datetime.now().date()
        assert f'<a href="https://foo.baa">{todaysdate}</a>' in content
        assert f'Block edited by {user.name}: {self.block.guid}' in content
        assert f'versions 0 - {self.addon.current_version.version}' in content
        assert f'Included in legacy blocklist' in content

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

    def test_can_delete(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
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
            self.single_url + '?guid=guid@', follow=True)
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
