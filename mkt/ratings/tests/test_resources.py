import json

from django.conf import settings

from mock import patch
from nose.tools import eq_

import amo
from addons.models import AddonUser
from amo.tests import AMOPaths
from reviews.models import Review
from users.models import UserProfile

from mkt.api.base import get_url, list_url
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


@patch.object(settings, 'SITE_URL', 'http://api/')
class TestRatingResource(BaseOAuth, AMOPaths):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestRatingResource, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=2519)
        self.collection_url = ('api_dispatch_list',
                               {'resource_name': 'rating'},
                               {'app': self.app.pk})

    def test_get(self):
        AddonUser.objects.create(user=self.user, addon=self.app)
        res = self.client.get(self.collection_url)
        data = json.loads(res.content)
        eq_(data['info']['average'], self.app.average_rating)
        eq_(data['info']['slug'], self.app.app_slug)
        assert not data['user']['can_rate']
        assert not data['user']['has_rated']

    def test_non_owner(self):
        res = self.client.get(self.collection_url)
        data = json.loads(res.content)
        assert data['user']['can_rate']
        assert not data['user']['has_rated']

    def test_already_rated(self):
        Review.objects.create(addon=self.app, user=self.user, body="yes")
        res = self.client.get(self.collection_url)
        data = json.loads(res.content)
        assert data['user']['can_rate']
        assert data['user']['has_rated']

    def _create(self, data=None):
        default_data = {
            'app': self.app.id,
            'body': 'Rocking the free web.',
            'rating': 5
        }
        if data:
            default_data.update(data)
        json_data = json.dumps(default_data)
        res = self.client.post(list_url('rating'), data=json_data)
        try:
            res_data = json.loads(res.content)
        except ValueError:
            res_data = res.content
        return res, res_data

    def test_create(self):
        res, data = self._create()
        eq_(201, res.status_code)
        assert data['resource_uri']

    def test_create_bad_data(self):
        """
        Let's run one test to ensure that ReviewForm is doing its data
        validation duties. We'll rely on the ReviewForm tests to ensure that the
        specifics are correct.
        """
        res, data = self._create({'body': None})
        eq_(400, res.status_code)
        assert 'body' in data['error_message']

    def test_create_nonexistant_app(self):
        res, data = self._create({'app': -1})
        eq_(400, res.status_code)
        assert 'app' in data['error_message']

    def test_create_duplicate_rating(self):
        self._create()
        res, data = self._create()
        eq_(409, res.status_code)

    def test_create_own_app(self):
        AddonUser.objects.create(user=self.user, addon=self.app)
        res, data = self._create()
        eq_(403, res.status_code)

    def test_rate_unpurchased_premium(self):
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        res, data = self._create()
        eq_(403, res.status_code)

    def _update(self, updated_data):
        # Create the original review
        default_data = {
            'body': 'Rocking the free web.',
            'rating': 5
        }
        res, res_data = self._create(default_data)

        # Update the review
        default_data.update(updated_data)
        review = Review.objects.all()[0]
        json_data = json.dumps(default_data)
        res = self.client.put(get_url('rating', review.pk), data=json_data)
        try:
            res_data = json.loads(res.content)
        except ValueError:
            res_data = res.content
        return res, res_data

    def test_update(self):
        new_data = {
            'body': 'Totally rocking the free web.',
            'rating': 4
        }
        res, data = self._update(new_data)
        eq_(res.status_code, 202)
        eq_(data['body'], new_data['body'])
        eq_(data['rating'], new_data['rating'])

    def test_update_bad_data(self):
        """
        Let's run one test to ensure that ReviewForm is doing its data
        validation duties. We'll rely on the ReviewForm tests to ensure that the
        specifics are correct.
        """
        res, data = self._update({'body': None})
        eq_(400, res.status_code)
        assert 'body' in data['error_message']

    def test_update_change_app(self):
        res, data = self._update({'app': -1})
        eq_(res.status_code, 400)

    def test_delete_app_mine(self):
        AddonUser.objects.filter(addon=self.app).update(user=self.user)
        user2 = UserProfile.objects.get(pk=31337)
        r = Review.objects.create(addon=self.app, user=user2, body="yes")
        res = self.client.delete(get_url('rating', r.pk))
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)

    def test_delete_comment_mine(self):
        r = Review.objects.create(addon=self.app, user=self.user, body="yes")
        res = self.client.delete(get_url('rating', r.pk))
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)

    def test_delete_addons_admin(self):
        user2 = UserProfile.objects.get(pk=31337)
        r = Review.objects.create(addon=self.app, user=user2, body="yes")
        self.grant_permission(self.user, 'Addons:Edit')
        res = self.client.delete(get_url('rating', r.pk))
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)

    def test_delete_users_admin(self):
        user2 = UserProfile.objects.get(pk=31337)
        r = Review.objects.create(addon=self.app, user=user2, body="yes")
        self.grant_permission(self.user, 'Users:Edit')
        res = self.client.delete(get_url('rating', r.pk))
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)

    def test_delete_not_mine(self):
        user2 = UserProfile.objects.get(pk=31337)
        r = Review.objects.create(addon=self.app, user=user2, body="yes")
        url = ('api_dispatch_detail', {'resource_name': 'rating', 'pk': r.pk})
        self.app.authors.clear()
        res = self.client.delete(url)
        eq_(res.status_code, 403)
        eq_(Review.objects.count(), 1)

    def test_delete_not_there(self):
        url = ('api_dispatch_detail',
               {'resource_name': 'rating', 'pk': 123})
        res = self.client.delete(url)
        eq_(res.status_code, 404)
