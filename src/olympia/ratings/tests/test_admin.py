# -*- coding: utf-8 -*-
from django.urls import reverse

from pyquery import PyQuery as pq

from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, user_factory
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile


class TestRatingAdmin(TestCase):
    fixtures = ['base/addon_3615', 'base/user_999']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.rating = Rating.objects.create(
            addon=self.addon, body=u'Bär', rating=5, user=user_factory())
        self.detail_url = reverse(
            'admin:ratings_rating_change', args=(self.rating.pk, ))
        self.list_url = reverse('admin:ratings_rating_changelist')
        self.delete_url = reverse(
            'admin:ratings_rating_delete', args=(self.rating.pk, )
        )

    def test_list(self):
        addon = Addon.objects.get(pk=3615)
        user = UserProfile.objects.get(pk=999)

        # Create a few more ratings.
        Rating.objects.create(
            addon=addon, user=user_factory(), rating=4,
            body=u'Lôrem ipsum dolor sit amet, per at melius fuisset '
                 u'invidunt, ea facete aperiam his. Et cum iusto detracto, '
                 u'nam atqui nostrum no, eum altera indoctum ad. Has ut duis '
                 u'tractatos laboramus, cum sale primis ei. Ius inimicus '
                 u'intellegebat ea, mollis expetendis usu ei. Cetero aeterno '
                 u'nostrud eu për.')
        Rating.objects.create(
            addon=addon, body=u'Fôo', rating=5, user=user_factory())
        # Create a reply.
        Rating.objects.create(
            addon=addon, user=user, body=u'Réply', reply_to=self.rating)

        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Ratings:Moderate')

        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 4

        # Test truncated text while we're at it.
        assert (
            u'Lôrem ipsum dolor sit amet, per at melius fuisset invidunt, ea '
            u'facete aperiam his. Et cum iusto detracto, nam atqui nostrum no,'
            u' eum altera...'
            in response.content.decode('utf-8'))

        response = self.client.get(
            self.list_url, {'type': 'rating'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 3

        response = self.client.get(
            self.list_url, {'type': 'reply'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1

    def test_can_not_access_detail_without_ratings_moderate_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 403

    def test_can_not_delete_without_admin_advanced_permission(self):
        assert Rating.objects.count() == 1
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Ratings:Moderate')  # Not enough!
        self.client.login(email=user.email)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(self.delete_url, {'post': 'yes'},
                                    follow=True)
        assert response.status_code == 403

        assert Rating.objects.count() == 1
        assert Rating.unfiltered.count() == 1

    def test_can_delete_with_admin_advanced_permission(self):
        assert Rating.objects.count() == 1
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Advanced')
        self.grant_permission(user, 'Ratings:Moderate')
        self.client.login(email=user.email)

        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert 'Delete selected rating' in response.content

        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 200
        assert 'Cannot delete rating' not in response.content
        response = self.client.post(self.delete_url, {'post': 'yes'},
                                    follow=True)
        assert response.status_code == 200

        assert Rating.objects.count() == 0
        assert Rating.unfiltered.count() == 1

    def test_detail(self):
        user = UserProfile.objects.get(pk=999)
        self.grant_permission(user, 'Admin:Advanced')
        self.grant_permission(user, 'Ratings:Moderate')
        self.client.login(email=user.email)

        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
