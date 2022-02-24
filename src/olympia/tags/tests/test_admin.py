from django.urls import reverse

from olympia.amo.tests import TestCase, user_factory

from ..models import Tag


class TestTagAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:tags_tag_changelist')

    def test_can_list_with_discovery_edit_permission(self):
        item = Tag.objects.all().first()
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert item.tag_text in response.content.decode('utf-8')

    def test_can_edit_with_discovery_edit_permission(self):
        item = Tag.objects.all().first()
        tag_count = Tag.objects.count()
        self.detail_url = reverse('admin:tags_tag_change', args=(item.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert item.tag_text in content

        response = self.client.post(
            self.detail_url,
            {
                'enable_for_random_shelf': False,
                'tag_text': 'Néw Text!',
            },
            follow=True,
        )
        assert response.status_code == 200
        item.reload()
        assert Tag.objects.count() == tag_count
        assert item.tag_text == 'Néw Text!'
        assert item.enable_for_random_shelf is False

    def test_can_delete_with_discovery_edit_permission(self):
        item = Tag.objects.all().first()
        self.delete_url = reverse('admin:tags_tag_delete', args=(item.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        # Can access delete confirmation page.
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 200
        assert Tag.objects.filter(pk=item.pk).exists()

        # Can actually delete.
        response = self.client.post(self.delete_url, {'post': 'yes'}, follow=True)
        assert response.status_code == 200
        assert not Tag.objects.filter(pk=item.pk).exists()

    def test_can_add_with_discovery_edit_permission(self):
        tag_count = Tag.objects.count()
        self.add_url = reverse('admin:tags_tag_add')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.add_url, follow=True)
        assert response.status_code == 200
        assert Tag.objects.count() == tag_count
        response = self.client.post(
            self.add_url,
            {
                'enable_for_random_shelf': True,
                'tag_text': 'Néw Tag!',
            },
            follow=True,
        )
        assert response.status_code == 200
        assert Tag.objects.count() == tag_count + 1
        item = Tag.objects.order_by('-created').first()
        assert item.tag_text == 'Néw Tag!'
        assert item.enable_for_random_shelf is True

    def test_can_not_add_without_discovery_edit_permission(self):
        tag_count = Tag.objects.count()
        self.add_url = reverse('admin:tags_tag_add')
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(self.add_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(
            self.add_url,
            {
                'enable_for_random_shelf': False,
                'tag_text': 'Néw Text!',
            },
            follow=True,
        )
        assert response.status_code == 403
        assert Tag.objects.count() == tag_count

    def test_can_not_edit_without_discovery_edit_permission(self):
        tag_count = Tag.objects.count()
        item = Tag.objects.all().first()
        self.detail_url = reverse('admin:tags_tag_change', args=(item.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 403

        response = self.client.post(
            self.detail_url,
            {
                'enable_for_random_shelf': False,
                'tag_text': 'Néw Text!',
            },
            follow=True,
        )
        assert response.status_code == 403
        item.reload()
        assert Tag.objects.count() == tag_count
        assert item.tag_text != 'Néw Text!'
        assert item.enable_for_random_shelf is True

    def test_can_not_delete_without_discovery_edit_permission(self):
        item = Tag.objects.all().first()
        self.delete_url = reverse('admin:tags_tag_delete', args=(item.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)
        # Can not access delete confirmation page.
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403
        assert Tag.objects.filter(pk=item.pk).exists()

        # Can not actually delete either.
        response = self.client.post(self.delete_url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 403
        assert Tag.objects.filter(pk=item.pk).exists()
