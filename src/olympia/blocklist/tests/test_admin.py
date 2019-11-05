from pyquery import PyQuery as pq

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

        # Create the block
        response = self.client.post(
            self.single_url + '?guid=guid@', {
                'min_version': '0',
                'max_version': addon.current_version.version,
                'url': 'dfd',
                'reason': 'some reason',
                '_save': 'Save',
            },
            follow=True)
        assert response.status_code == 200
        assert Block.objects.count() == 1
        assert Block.objects.first().addon == addon

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
