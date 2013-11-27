# -*- coding: utf-8 -*-
from datetime import datetime
import json
from urlparse import urlparse

from django.core.urlresolvers import reverse
from django.http import QueryDict

from mock import patch
from nose.tools import eq_, ok_

import amo
from addons.models import AddonUser
from devhub.models import ActivityLog
from market.models import AddonPurchase
from reviews.models import Review, ReviewFlag
from users.models import UserProfile

import mkt.regions
from mkt.api.tests.test_oauth import RestOAuth
from mkt.site.fixtures import fixture
from mkt.webapps.models import AddonExcludedRegion, Webapp


class TestRatingResource(RestOAuth, amo.tests.AMOPaths):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestRatingResource, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=2519)
        self.user2 = UserProfile.objects.get(pk=31337)
        self.list_url = reverse('ratings-list')

    def _get_url(self, url, client=None, **kwargs):
        if client is None:
            client = self.client
        res = client.get(url, kwargs)
        data = json.loads(res.content)
        return res, data

    def _get_filter(self, client=None, expected_status=200, **params):
        res, data = self._get_url(self.list_url, client=client, **params)
        eq_(res.status_code, expected_status)
        if expected_status == 200:
            eq_(len(data['objects']), 1)
        return res, data

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.list_url),
                        'get', 'post', 'put', 'delete')

    def test_options(self):
        res = self.anon.options(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        ok_('application/json' in data['renders'])
        ok_('application/json' in data['parses'])

    def test_get_empty_with_app(self):
        AddonUser.objects.create(user=self.user, addon=self.app)
        res, data = self._get_url(self.list_url, app=self.app.pk)
        eq_(res.status_code, 200)
        eq_(data['info']['average'], self.app.average_rating)
        eq_(data['info']['slug'], self.app.app_slug)
        assert not data['user']['can_rate']
        assert not data['user']['has_rated']

    def test_get(self):
        first_version = self.app.current_version
        rev = Review.objects.create(addon=self.app, user=self.user,
                                    version=first_version,
                                    body=u'I lôve this app',
                                    rating=5)
        pk = rev.pk
        ver = amo.tests.version_factory(addon=self.app, version='2.0',
                                        file_kw=dict(status=amo.STATUS_PUBLIC))
        self.app.update_version()
        res, data = self._get_url(self.list_url, app=self.app.pk)

        eq_(data['info']['average'], self.app.average_rating)
        eq_(data['info']['slug'], self.app.app_slug)
        eq_(data['info']['current_version'], ver.version)
        eq_(data['user']['can_rate'], True)
        eq_(data['user']['has_rated'], True)
        eq_(len(data['objects']), 1)
        eq_(data['objects'][0]['app'], '/api/apps/app/337141/')
        eq_(data['objects'][0]['body'], rev.body)
        eq_(data['objects'][0]['created'],
            rev.created.replace(microsecond=0).isoformat())
        eq_(data['objects'][0]['is_author'], True)
        eq_(data['objects'][0]['modified'],
            rev.modified.replace(microsecond=0).isoformat())
        eq_(data['objects'][0]['rating'], rev.rating)
        eq_(data['objects'][0]['report_spam'],
            reverse('ratings-flag', kwargs={'pk': pk}))
        eq_(data['objects'][0]['resource_uri'],
            reverse('ratings-detail', kwargs={'pk': pk}))
        eq_(data['objects'][0]['user']['display_name'], self.user.display_name)
        eq_(data['objects'][0]['version']['version'], first_version.version)
        eq_(data['objects'][0]['version']['resource_uri'],
            reverse('version-detail', kwargs={'pk': first_version.pk}))

    def test_is_flagged_false(self):
        Review.objects.create(addon=self.app, user=self.user2, body='yes')
        res, data = self._get_url(self.list_url, app=self.app.pk)
        eq_(data['objects'][0]['is_author'], False)
        eq_(data['objects'][0]['has_flagged'], False)

    def test_is_flagged_is_author(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res, data = self._get_url(self.list_url, app=self.app.pk)
        eq_(data['objects'][0]['is_author'], True)
        eq_(data['objects'][0]['has_flagged'], False)

    def test_is_flagged_true(self):
        rat = Review.objects.create(addon=self.app, user=self.user2, body='ah')
        ReviewFlag.objects.create(review=rat, user=self.user,
                                  flag=ReviewFlag.SPAM)
        res, data = self._get_url(self.list_url, app=self.app.pk)
        eq_(data['objects'][0]['is_author'], False)
        eq_(data['objects'][0]['has_flagged'], True)

    def test_get_detail(self):
        fmt = '%Y-%m-%dT%H:%M:%S'
        Review.objects.create(addon=self.app, user=self.user2, body='no')
        rev = Review.objects.create(addon=self.app, user=self.user, body='yes')
        url = reverse('ratings-detail', kwargs={'pk': rev.pk})
        res, data = self._get_url(url)
        self.assertCloseToNow(datetime.strptime(data['modified'], fmt))
        self.assertCloseToNow(datetime.strptime(data['created'], fmt))
        eq_(data['body'], 'yes')

    def test_filter_self(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        Review.objects.create(addon=self.app, user=self.user2, body='no')
        self._get_filter(user=self.user.pk)

    def test_filter_mine(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        Review.objects.create(addon=self.app, user=self.user2, body='no')
        self._get_filter(user='mine')

    def test_filter_mine_anonymous(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        self._get_filter(user='mine', client=self.anon, expected_status=403)

    def test_filter_by_app_slug(self):
        self.app2 = amo.tests.app_factory()
        Review.objects.create(addon=self.app2, user=self.user, body='no')
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res, data = self._get_filter(app=self.app.app_slug)
        eq_(data['info']['slug'], self.app.app_slug)
        eq_(data['info']['current_version'], self.app.current_version.version)

    def test_filter_by_app_pk(self):
        self.app2 = amo.tests.app_factory()
        Review.objects.create(addon=self.app2, user=self.user, body='no')
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res, data = self._get_filter(app=self.app.pk)
        eq_(data['info']['slug'], self.app.app_slug)
        eq_(data['info']['current_version'], self.app.current_version.version)

    def test_filter_by_invalid_app_slug(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        self._get_filter(app='wrongslug', expected_status=400)

    def test_filter_by_nonpublic_app(self):
        self.app.update(status=amo.STATUS_PENDING)
        self._get_filter(app=self.app.app_slug, expected_status=400)

    @patch('mkt.ratings.serializers.get_region')
    def test_filter_by_app_excluded_in_region(self, get_region_mock):
        AddonExcludedRegion.objects.create(addon=self.app,
                                           region=mkt.regions.BR.id)
        get_region_mock.return_value = 'br'
        r, data = self._get_filter(app=self.app.app_slug, expected_status=400)
        eq_(data['detail'], 'App not available in this region')

    def test_anonymous_get_list_without_app(self):
        res, data = self._get_url(self.list_url, client=self.anon)
        eq_(res.status_code, 200)
        assert not 'user' in data

    def test_anonymous_get_list_app(self):
        res, data = self._get_url(self.list_url, app=self.app.app_slug,
                                  client=self.anon)
        eq_(res.status_code, 200)
        eq_(data['user'], None)

    def test_non_owner(self):
        res, data = self._get_url(self.list_url, app=self.app.app_slug)
        assert data['user']['can_rate']
        assert not data['user']['has_rated']

    def test_can_rate_unpurchased(self):
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        res, data = self._get_url(self.list_url, app=self.app.app_slug)
        assert not res.json['user']['can_rate']

    def test_can_rate_purchased(self):
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        AddonPurchase.objects.create(addon=self.app, user=self.user)
        res, data = self._get_url(self.list_url, app=self.app.app_slug)
        assert res.json['user']['can_rate']

    def test_isowner_true(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res, data = self._get_url(self.list_url, app=self.app.app_slug)
        data = json.loads(res.content)
        eq_(data['objects'][0]['is_author'], True)

    def test_isowner_false(self):
        Review.objects.create(addon=self.app, user=self.user2, body='yes')
        res, data = self._get_url(self.list_url, app=self.app.app_slug)
        data = json.loads(res.content)
        eq_(data['objects'][0]['is_author'], False)

    def test_isowner_anonymous(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res, data = self._get_url(self.list_url, app=self.app.app_slug,
                                  client=self.anon)
        data = json.loads(res.content)
        self.assertNotIn('is_author', data['objects'][0])

    def test_already_rated(self):
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        res, data = self._get_url(self.list_url, app=self.app.app_slug)
        data = json.loads(res.content)
        assert data['user']['can_rate']
        assert data['user']['has_rated']

    def test_already_rated_version(self):
        self.app.update(is_packaged=True)
        Review.objects.create(addon=self.app, user=self.user, body='yes')
        amo.tests.version_factory(addon=self.app, version='3.0')
        self.app.update_version()
        res, data = self._get_url(self.list_url, app=self.app.app_slug)
        data = json.loads(res.content)
        assert data['user']['can_rate']
        assert not data['user']['has_rated']

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
        res = client.post(self.list_url, data=json_data)
        try:
            res_data = json.loads(res.content)
        except ValueError:
            res_data = res.content
        return res, res_data

    def test_anonymous_create_fails(self):
        res, data = self._create(anonymous=True)
        eq_(res.status_code, 403)

    @patch('mkt.ratings.views.record_action')
    def test_create(self, record_action):
        log_review_id = amo.LOG.ADD_REVIEW.id
        eq_(ActivityLog.objects.filter(action=log_review_id).count(), 0)
        res, data = self._create()
        eq_(201, res.status_code)
        pk = Review.objects.latest('pk').pk
        eq_(data['body'], 'Rocking the free web.')
        eq_(data['rating'], 5)
        eq_(data['resource_uri'], reverse('ratings-detail', kwargs={'pk': pk}))
        eq_(data['report_spam'], reverse('ratings-flag', kwargs={'pk': pk}))

        eq_(record_action.call_count, 1)
        eq_(record_action.call_args[0][0], 'new-review')
        eq_(record_action.call_args[0][2], {'app-id': 337141})
        eq_(ActivityLog.objects.filter(action=log_review_id).count(), 1)

        return res, data

    def test_create_packaged(self):
        self.app.update(is_packaged=True)
        res, data = self.test_create()
        eq_(data['version']['version'], '1.0')

    def test_create_bad_data(self):
        res, data = self._create({'body': None})
        eq_(400, res.status_code)
        assert 'body' in data

    def test_create_nonexistent_app(self):
        res, data = self._create({'app': -1})
        eq_(400, res.status_code)
        assert 'app' in data

    @patch('mkt.ratings.serializers.get_region')
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
        version = amo.tests.version_factory(addon=self.app, version='3.0')
        self.app.update_version()
        eq_(self.app.reload().current_version, version)
        res, data = self._create()
        eq_(201, res.status_code)
        eq_(data['version']['version'], '3.0')

    def test_create_duplicate_rating_packaged(self):
        self.app.update(is_packaged=True)
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

    def test_rate_purchased_premium(self):
        self.app.update(premium_type=amo.ADDON_PREMIUM)
        AddonPurchase.objects.create(addon=self.app, user=self.user)
        res, data = self._create()
        eq_(201, res.status_code)

    def _create_default_review(self):
        # Create the original review
        default_data = {
            'body': 'Rocking the free web.',
            'rating': 5
        }
        res, res_data = self._create(default_data)
        return res, res_data

    def test_patch_not_implemented(self):
        self._create_default_review()
        pk = Review.objects.latest('id').pk
        json_data = json.dumps({
            'body': 'Totally rocking the free web.',
        })
        res = self.client.patch(reverse('ratings-detail', kwargs={'pk': pk}),
                                data=json_data)
        # Should return a 405 but permission check is done first. It's fine.
        eq_(res.status_code, 403)

    def _update(self, updated_data, pk=None):
        # Update the review
        if pk is None:
            pk = Review.objects.latest('id').pk
        json_data = json.dumps(updated_data)
        res = self.client.put(reverse('ratings-detail', kwargs={'pk': pk}),
                              data=json_data)
        try:
            res_data = json.loads(res.content)
        except ValueError:
            res_data = res.content
        return res, res_data

    def test_update(self):
        self._create_default_review()
        new_data = {
            'body': 'Totally rocking the free web.',
            'rating': 4,
        }
        log_review_id = amo.LOG.EDIT_REVIEW.id
        eq_(ActivityLog.objects.filter(action=log_review_id).count(), 0)
        res, data = self._update(new_data)
        eq_(res.status_code, 200)
        eq_(data['body'], new_data['body'])
        eq_(data['rating'], new_data['rating'])
        eq_(ActivityLog.objects.filter(action=log_review_id).count(), 1)

    def test_update_bad_data(self):
        self._create_default_review()
        res, data = self._update({'body': None})
        eq_(400, res.status_code)
        assert 'body' in data

    def test_update_change_app(self):
        _, previous_data = self._create_default_review()
        self.app2 = amo.tests.app_factory()
        new_data = {
            'body': 'Totally rocking the free web.',
            'rating': 4,
            'app': self.app2.pk
        }
        res, data = self._update(new_data)
        eq_(res.status_code, 200)
        eq_(data['body'], new_data['body'])
        eq_(data['rating'], new_data['rating'])
        eq_(data['app'], previous_data['app'])

    def test_update_comment_not_mine(self):
        rev = Review.objects.create(addon=self.app, user=self.user2,
                                    body='yes')
        res = self.client.put(reverse('ratings-detail', kwargs={'pk': rev.pk}),
                              json.dumps({'body': 'no', 'rating': 1}))
        eq_(res.status_code, 403)
        rev.reload()
        eq_(rev.body, 'yes')

    def test_delete_app_mine(self):
        AddonUser.objects.filter(addon=self.app).update(user=self.user)
        rev = Review.objects.create(addon=self.app, user=self.user2, 
                                    body='yes')
        url = reverse('ratings-detail', kwargs={'pk': rev.pk})
        res = self.client.delete(url)
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)
        log_review_id = amo.LOG.DELETE_REVIEW.id
        eq_(ActivityLog.objects.filter(action=log_review_id).count(), 1)

    def test_delete_comment_mine(self):
        rev = Review.objects.create(addon=self.app, user=self.user, body='yes')
        url = reverse('ratings-detail', kwargs={'pk': rev.pk})
        res = self.client.delete(url)
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)
        log_review_id = amo.LOG.DELETE_REVIEW.id
        eq_(ActivityLog.objects.filter(action=log_review_id).count(), 1)

    def test_delete_addons_admin(self):
        self.grant_permission(self.user, 'Addons:Edit')
        rev = Review.objects.create(addon=self.app, user=self.user2,
                                    body='yes')
        url = reverse('ratings-detail', kwargs={'pk': rev.pk})
        res = self.client.delete(url)
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)
        log_review_id = amo.LOG.DELETE_REVIEW.id
        eq_(ActivityLog.objects.filter(action=log_review_id).count(), 1)

    def test_delete_users_admin(self):
        self.grant_permission(self.user, 'Users:Edit')
        rev = Review.objects.create(addon=self.app, user=self.user2,
                                    body='yes')
        url = reverse('ratings-detail', kwargs={'pk': rev.pk})
        res = self.client.delete(url)
        eq_(res.status_code, 204)
        eq_(Review.objects.count(), 0)
        log_review_id = amo.LOG.DELETE_REVIEW.id
        eq_(ActivityLog.objects.filter(action=log_review_id).count(), 1)

    def test_delete_not_mine(self):
        rev = Review.objects.create(addon=self.app, user=self.user2,
                                    body='yes')
        url = reverse('ratings-detail', kwargs={'pk': rev.pk})
        self.app.authors.clear()
        res = self.client.delete(url)
        eq_(res.status_code, 403)
        eq_(Review.objects.count(), 1)
        log_review_id = amo.LOG.DELETE_REVIEW.id
        eq_(ActivityLog.objects.filter(action=log_review_id).count(), 0)

    def test_delete_not_there(self):
        url = reverse('ratings-detail', kwargs={'pk': 123})
        res = self.client.delete(url)
        eq_(res.status_code, 404)
        log_review_id = amo.LOG.DELETE_REVIEW.id
        eq_(ActivityLog.objects.filter(action=log_review_id).count(), 0)


class TestRatingResourcePagination(RestOAuth, amo.tests.AMOPaths):
    fixtures = fixture('user_2519', 'user_999', 'webapp_337141')

    def setUp(self):
        super(TestRatingResourcePagination, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=2519)
        self.user2 = UserProfile.objects.get(pk=31337)
        self.user3 = UserProfile.objects.get(pk=999)
        self.url = reverse('ratings-list')

    def test_pagination(self):
        first_version = self.app.current_version
        rev1 = Review.objects.create(addon=self.app, user=self.user,
                                     version=first_version,
                                     body=u'I häte this app',
                                     rating=0)
        rev2 = Review.objects.create(addon=self.app, user=self.user2,
                                     version=first_version,
                                     body=u'I lôve this app',
                                     rating=5)
        rev3 = Review.objects.create(addon=self.app, user=self.user3,
                                     version=first_version,
                                     body=u'Blurp.',
                                     rating=3)
        rev1.update(created=self.days_ago(3))
        rev2.update(created=self.days_ago(2))
        res = self.client.get(self.url, {'limit': 2})
        eq_(res.status_code, 200)
        data = json.loads(res.content)

        eq_(len(data['objects']), 2)
        eq_(data['objects'][0]['body'], rev3.body)
        eq_(data['objects'][1]['body'], rev2.body)
        eq_(data['meta']['total_count'], 3)
        eq_(data['meta']['limit'], 2)
        eq_(data['meta']['previous'], None)
        eq_(data['meta']['offset'], 0)
        next = urlparse(data['meta']['next'])
        eq_(next.path, self.url)
        eq_(QueryDict(next.query).dict(), {u'limit': u'2', u'offset': u'2'})

        res = self.client.get(self.url, {'limit': 2, 'offset': 2})
        eq_(res.status_code, 200)
        data = json.loads(res.content)

        eq_(len(data['objects']), 1)
        eq_(data['objects'][0]['body'], rev1.body)
        eq_(data['meta']['total_count'], 3)
        eq_(data['meta']['limit'], 2)
        prev = urlparse(data['meta']['previous'])
        eq_(next.path, self.url)
        eq_(QueryDict(prev.query).dict(), {u'limit': u'2', u'offset': u'0'})
        eq_(data['meta']['offset'], 2)
        eq_(data['meta']['next'], None)

    def test_total_count(self):
        self.app.update(total_reviews=10)
        res = self.client.get(self.url)
        data = json.loads(res.content)

        # We know we have no results, total_reviews isn't used.
        eq_(data['meta']['total_count'], 0)

        Review.objects.create(addon=self.app, user=self.user,
                      version=self.app.current_version,
                      body=u'I häte this app',
                      rating=0)
        self.app.update(total_reviews=10)
        res = self.client.get(self.url)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 10)


class TestReviewFlagResource(RestOAuth, amo.tests.AMOPaths):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestReviewFlagResource, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=2519)
        self.user2 = UserProfile.objects.get(pk=31337)
        self.rating = Review.objects.create(addon=self.app,
                                            user=self.user2, body='yes')
        self.flag_url = reverse('ratings-flag', kwargs={'pk': self.rating.pk})

    def test_has_cors(self):
        self.assertCORS(self.client.post(self.flag_url), 'post')

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
