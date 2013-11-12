# -*- coding: utf-8 -*-
from datetime import datetime
import json

from mock import patch
from nose.tools import eq_

import amo
from addons.models import AddonUser
from amo.tests import AMOPaths, version_factory
from market.models import AddonPurchase
from reviews.models import Review, ReviewFlag
from users.models import UserProfile
from versions.models import Version

import mkt.regions
from mkt.api.base import get_url, list_url
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.site.fixtures import fixture
from mkt.webapps.models import AddonExcludedRegion, Webapp


class TestRatingResource(BaseOAuth, AMOPaths):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestRatingResource, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=2519)
        self.user2 = UserProfile.objects.get(pk=31337)

    def _collection_url(self, **kwargs):
        data = {'app': self.app.pk}
        if kwargs:
            data.update(kwargs)
        return ('api_dispatch_list', {'resource_name': 'rating'}, data)

    def test_has_cors(self):
        self.assertCORS(self.client.get(self._collection_url()), 'get', 'post')

    def test_get_empty(self):
        AddonUser.objects.create(user=self.user, addon=self.app)
        res = self.client.get(self._collection_url())
        data = json.loads(res.content)
        eq_(data['info']['average'], self.app.average_rating)
        eq_(data['info']['slug'], self.app.app_slug)
        assert not data['user']['can_rate']
        assert not data['user']['has_rated']

    def test_get(self):
        first_version = self.app.current_version
        rev = Review.objects.create(addon=self.app, user=self.user,
                                    version=first_version,
                                    body=u'I lôve this app',
                                    rating=0)
        ver = version_factory(addon=self.app, version='2.0',
                              file_kw=dict(status=amo.STATUS_PUBLIC))
        self.app.update_version()
        res = self.client.get(self._collection_url())
        data = json.loads(res.content)

        eq_(data['info']['average'], self.app.average_rating)
        eq_(data['info']['slug'], self.app.app_slug)
        eq_(data['info']['current_version'], ver.version)
        eq_(data['user']['can_rate'], True)
        eq_(data['user']['has_rated'], True)
        eq_(len(data['objects']), 1)
        eq_(data['objects'][0]['body'], rev.body)
        eq_(data['objects'][0]['rating'], rev.rating)
        eq_(data['objects'][0]['version']['version'], first_version.version)

    def test_is_flagged_false(self):
        Review.objects.create(addon=self.app, user=self.user2, body='yes')
        res = self.client.get(self._collection_url())
        data = json.loads(res.content)
        eq_(data['objects'][0]['is_author'], False)
        eq_(data['objects'][0]['has_flagged'], False)

    def test_is_flagged_is_author(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res = self.client.get(self._collection_url())
        data = json.loads(res.content)
        eq_(data['objects'][0]['is_author'], True)
        eq_(data['objects'][0]['has_flagged'], False)

    def test_is_flagged_true(self):
        rat = Review.objects.create(addon=self.app, user=self.user2, body='ah')
        ReviewFlag.objects.create(review=rat, user=self.user,
                                  flag=ReviewFlag.SPAM)
        res = self.client.get(self._collection_url())
        data = json.loads(res.content)
        eq_(data['objects'][0]['is_author'], False)
        eq_(data['objects'][0]['has_flagged'], True)

    def _get_single(self, **kwargs):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        url = self._collection_url(**kwargs)
        res = self.client.get(url)
        data = json.loads(res.content)
        return res, data

    def test_get_by_pk(self):
        res, data = self._get_single()
        eq_(len(data['objects']), 1)
        eq_(data['info']['slug'], self.app.app_slug)
        eq_(data['info']['current_version'], self.app.current_version.version)

    def test_get_timestamps(self):
        fmt = '%Y-%m-%dT%H:%M:%S'
        rev = Review.objects.create(addon=self.app, user=self.user, body='yes')
        res = self.client.get(get_url('rating', rev.pk))
        data = json.loads(res.content)
        self.assertCloseToNow(datetime.strptime(data['modified'], fmt))
        self.assertCloseToNow(datetime.strptime(data['created'], fmt))

    def _get_filter(self, client, key):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res = client.get(list_url('rating') + ({'user': key},))
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['meta']['total_count'], 1)

    def test_filter_self(self):
        self._get_filter(self.client, self.user.pk)

    def test_filter_mine(self):
        self._get_filter(self.client, 'mine')

    def test_filter_not_mine(self):
        res = self.anon.get(list_url('rating') + ({'user': 'mine'},))
        eq_(res.status_code, 401)

    def test_get_by_slug(self):
        res, data = self._get_single(app=self.app.app_slug)
        eq_(len(data['objects']), 1)
        eq_(data['info']['slug'], self.app.app_slug)
        eq_(data['info']['current_version'], self.app.current_version.version)

    def test_get_nonpublic(self):
        self.app.update(status=amo.STATUS_PENDING)
        res, data = self._get_single(app=self.app.app_slug)
        eq_(res.status_code, 400)

    @patch('mkt.ratings.resources.get_region')
    def test_get_nonregion(self, get_region_mock):
        AddonExcludedRegion.objects.create(addon=self.app,
                                           region=mkt.regions.BR.id)
        get_region_mock.return_value = 'br'
        res, data = self._get_single(app=self.app.app_slug)
        eq_(res.status_code, 400)

    def test_anonymous_get_list(self):
        res = self.anon.get(list_url('rating'))
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        assert 'user' not in data

    def test_anonymous_post_list_fails(self):
        res, data = self._create(anonymous=True)
        eq_(res.status_code, 401)

    def test_anonymous_get_detail(self):
        res = self.anon.get(self._collection_url())
        data = json.loads(res.content)
        eq_(res.status_code, 200)
        eq_(data['user'], None)

    def test_non_owner(self):
        res = self.client.get(self._collection_url())
        data = json.loads(res.content)
        assert data['user']['can_rate']
        assert not data['user']['has_rated']

    def test_isowner_true(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res = self.client.get(self._collection_url())
        data = json.loads(res.content)
        eq_(data['objects'][0]['is_author'], True)

    def test_isowner_false(self):
        Review.objects.create(addon=self.app, user=self.user2, body='yes')
        res = self.client.get(self._collection_url())
        data = json.loads(res.content)
        eq_(data['objects'][0]['is_author'], False)

    def test_isowner_anonymous(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res = self.anon.get(self._collection_url())
        data = json.loads(res.content)
        self.assertNotIn('is_author', data['objects'][0])

    def test_already_rated(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res = self.client.get(self._collection_url())
        data = json.loads(res.content)
        assert data['user']['can_rate']
        assert data['user']['has_rated']

    def test_can_rate_unpurchased(self):
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.get(self._collection_url())
        assert not res.json['user']['can_rate']

    def test_can_rate_purchased(self):
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        AddonPurchase.objects.create(addon=self.app, user=self.user)
        res = self.client.get(self._collection_url())
        assert res.json['user']['can_rate']

    def _create(self, data=None, anonymous=False):
        default_data = {
            'app': self.app.id,
            'body': 'Rocking the free web.',
            'rating': 5,
            'version': self.app.current_version.id
        }
        if data:
            default_data.update(data)
        json_data = json.dumps(default_data)
        client = self.anon if anonymous else self.client
        res = client.post(list_url('rating'), data=json_data)
        try:
            res_data = json.loads(res.content)
        except ValueError:
            res_data = res.content
        return res, res_data

    def test_create(self):
        res, data = self._create()
        eq_(201, res.status_code)
        assert data['resource_uri']
        eq_(data['report_spam'], data['resource_uri'] + 'flag/')

    def test_create_bad_data(self):
        """
        Let's run one test to ensure that ReviewForm is doing its data
        validation duties. We'll rely on the ReviewForm tests to ensure that
        the specifics are correct.
        """
        res, data = self._create({'body': None})
        eq_(400, res.status_code)
        assert 'body' in data['error_message']

    def test_create_nonexistent_app(self):
        res, data = self._create({'app': -1})
        eq_(400, res.status_code)
        assert 'app' in data['error_message']

    @patch('mkt.ratings.resources.get_region')
    def test_create_for_nonregion(self, get_region_mock):
        AddonExcludedRegion.objects.create(addon=self.app,
                                           region=mkt.regions.BR.id)
        get_region_mock.return_value = 'br'
        res, data = self._create()
        eq_(400, res.status_code)

    def test_create_for_nonpublic(self):
        self.app.update(status=amo.STATUS_PENDING)
        res, data = self._create()
        eq_(400, res.status_code)

    def test_create_duplicate_rating(self):
        self._create()
        res, data = self._create()
        eq_(409, res.status_code)

    def test_new_rating_for_new_version(self):
        self.app.update(is_packaged=True)
        self._create()
        vid = Version.objects.create(addon=self.app, version='3').id
        res, data = self._create(data={'version': vid})
        eq_(201, res.status_code)

    def test_new_rating_for_old_version(self):
        self.app.update(is_packaged=True)
        vid = self.app.latest_version.id
        self._create()
        Version.objects.create(addon=self.app, version='2')
        res, data = self._create(data={'version': vid})
        eq_(409, res.status_code)

    def test_create_own_app(self):
        AddonUser.objects.create(user=self.user, addon=self.app)
        res, data = self._create()
        eq_(403, res.status_code)

    def test_rate_unpurchased_premium(self):
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        res, data = self._create()
        eq_(403, res.status_code)

    def test_rate_purchased_premium(self):
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        AddonPurchase.objects.create(addon=self.app, user=self.user)
        res, data = self._create()
        eq_(201, res.status_code)

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
        validation duties. We'll rely on the ReviewForm tests to ensure that
        the specifics are correct.
        """
        res, data = self._update({'body': None})
        eq_(400, res.status_code)
        assert 'body' in data['error_message']

    def test_update_change_app(self):
        res, data = self._update({'app': -1})
        eq_(res.status_code, 400)

    def test_update_comment_not_mine(self):
        r = Review.objects.create(addon=self.app, user=self.user2, body='yes')
        res = self.client.put(get_url('rating', r.pk),
                              json.dumps({'body': 'no', 'rating': 1}))
        eq_(res.status_code, 403)

    def test_delete_app_mine(self):
        AddonUser.objects.filter(addon=self.app).update(user=self.user)
        user2 = UserProfile.objects.get(pk=31337)
        r = Review.objects.create(addon=self.app, user=user2, body='yes')
        res = self.client.delete(get_url('rating', r.pk))
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)

    def test_delete_comment_mine(self):
        r = Review.objects.create(addon=self.app, user=self.user, body='yes')
        res = self.client.delete(get_url('rating', r.pk))
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)

    def test_delete_addons_admin(self):
        user2 = UserProfile.objects.get(pk=31337)
        r = Review.objects.create(addon=self.app, user=user2, body='yes')
        self.grant_permission(self.user, 'Addons:Edit')
        res = self.client.delete(get_url('rating', r.pk))
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)

    def test_delete_users_admin(self):
        user2 = UserProfile.objects.get(pk=31337)
        r = Review.objects.create(addon=self.app, user=user2, body='yes')
        self.grant_permission(self.user, 'Users:Edit')
        res = self.client.delete(get_url('rating', r.pk))
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)

    def test_delete_not_mine(self):
        user2 = UserProfile.objects.get(pk=31337)
        r = Review.objects.create(addon=self.app, user=user2, body='yes')
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


class TestFireplaceRatingResource(BaseOAuth, AMOPaths):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestFireplaceRatingResource, self).setUp(api_name='fireplace')
        self.app = Webapp.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=2519)
        self.user2 = UserProfile.objects.get(pk=31337)


class TestReviewFlagResource(BaseOAuth, AMOPaths):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestReviewFlagResource, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=2519)
        self.user2 = UserProfile.objects.get(pk=31337)
        self.rating = Review.objects.create(addon=self.app,
                                            user=self.user2, body='yes')
        self.flag_url = ('api_post_flag',
                         {'resource_name': 'rating',
                          'review_id': self.rating.pk}, {})

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.flag_url), 'post')

    def test_flag(self):
        data = json.dumps({'flag': ReviewFlag.SPAM})
        res = self.client.post(self.flag_url, data=data)
        eq_(res.status_code, 201)
        rf = ReviewFlag.objects.get(review=self.rating)
        eq_(rf.user, self.user)
        eq_(rf.flag, ReviewFlag.SPAM)
        eq_(rf.note, '')

    def test_flag_note(self):
        note = 'do not want'
        data = json.dumps({'flag': ReviewFlag.SPAM, 'note': note})
        res = self.client.post(self.flag_url, data=data)
        eq_(res.status_code, 201)
        rf = ReviewFlag.objects.get(review=self.rating)
        eq_(rf.user, self.user)
        eq_(rf.flag, ReviewFlag.OTHER)
        eq_(rf.note, note)

    def test_flag_anon(self):
        data = json.dumps({'flag': ReviewFlag.SPAM})
        res = self.anon.post(self.flag_url, data=data)
        eq_(res.status_code, 201)
        rf = ReviewFlag.objects.get(review=self.rating)
        eq_(rf.user, None)
        eq_(rf.flag, ReviewFlag.SPAM)
        eq_(rf.note, '')

    def test_flag_conflict(self):
        data = json.dumps({'flag': ReviewFlag.SPAM})
        res = self.client.post(self.flag_url, data=data)
        res = self.client.post(self.flag_url, data=data)
        eq_(res.status_code, 409)
