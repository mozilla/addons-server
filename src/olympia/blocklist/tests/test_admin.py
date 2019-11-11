import datetime

from pyquery import PyQuery as pq

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import (
    TestCase, addon_factory, user_factory, version_factory)
from olympia.amo.urlresolvers import reverse

from ..models import Block


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
        Block.objects.create(addon=addon)
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Reviews:Admin')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert addon.guid in response.content.decode('utf-8')

    def test_can_not_list_without_permission(self):
        addon = addon_factory()
        Block.objects.create(addon=addon)
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
        self.multi_url = reverse('admin:blocklist_block_add_multiple')

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

        # An existing block will redirect to change view instead
        block = Block.objects.create(addon=addon)
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

        addon = addon_factory(guid='guid@', name='Danger Danger')
        response = self.client.get(
            self.single_url + '?guid=guid@', follow=True)
        content = response.content.decode('utf-8')
        assert 'Add-on GUIDs (one per line)' not in content
        assert 'guid@' in content
        assert 'Danger Danger' in content
        assert str(addon.average_daily_users) in content
        assert Block.objects.count() == 0  # Check we didn't create it already
        assert 'Block History' not in content  # Only shown for edits

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
        assert Block.objects.first().addon == addon
        log = ActivityLog.objects.for_addons(addon).last()
        assert log.action == amo.LOG.BLOCKLIST_BLOCK_ADDED.id
        assert log.arguments == [addon, addon.guid]
        assert log.details['min_version'] == '0'
        assert log.details['max_version'] == addon.current_version.version
        assert log.details['reason'] == 'some reason'

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


class TestBlockAdminEdit(TestCase):
    def setUp(self):
        self.addon = addon_factory(guid='guid@', name='Danger Danger')
        self.block = Block.objects.create(addon=self.addon)
        self.change_url = reverse(
            'admin:blocklist_block_change', args=(self.block.pk,))
        self.delete_url = reverse(
            'admin:blocklist_block_delete', args=(self.block.pk,))

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
        assert log.arguments == [self.addon, self.addon.guid]
        assert log.details['min_version'] == '0'
        assert log.details['max_version'] == self.addon.current_version.version
        assert log.details['reason'] == 'some other reason'

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
        assert log.arguments == [self.addon, self.addon.guid]

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
