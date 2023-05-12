import json

from datetime import timedelta
from ipaddress import IPv4Address

from django.conf import settings
from django.core import mail
from django.test.utils import override_settings
from django.utils.encoding import force_str

from freezegun import freeze_time
from rest_framework.exceptions import ErrorDetail

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.utils import generate_addon_guid
from olympia.amo.tests import (
    APITestClientSessionID,
    TestCase,
    addon_factory,
    get_random_ip,
    reverse_ns,
    user_factory,
    version_factory,
)
from olympia.users.models import (
    DisposableEmailDomainRestriction,
    EmailUserRestriction,
    IPNetworkUserRestriction,
    RESTRICTION_TYPES,
)

from ..models import DeniedRatingWord, Rating, RatingFlag
from ..tasks import addon_rating_aggregates
from ..views import RatingViewSet


locmem_cache = settings.CACHES.copy()
locmem_cache['default'][
    'BACKEND'
] = 'django.core.cache.backends.locmem.LocMemCache'  # noqa


class TestRatingViewSetGet(TestCase):
    client_class = APITestClientSessionID
    list_url_name = 'rating-list'
    detail_url_name = 'rating-detail'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.url = reverse_ns(self.list_url_name)

    def test_url_v3(self):
        assert reverse_ns('rating-list', api_version='v3').endswith(
            '/v3/reviews/review/'
        )
        rating = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory()
        )
        detail_url = reverse_ns(
            'rating-detail', api_version='v3', kwargs={'pk': rating.pk}
        )
        assert detail_url.endswith('/v3/reviews/review/%d/' % rating.pk)

    def test_url_default(self):
        assert self.url.endswith('/v5/ratings/rating/')
        rating = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory()
        )
        detail_url = reverse_ns(self.detail_url_name, kwargs={'pk': rating.pk})
        assert detail_url.endswith('/v5/ratings/rating/%d/' % rating.pk)

    def test_list_addon(self, **kwargs):
        review1 = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory(), rating=1
        )
        review2 = Rating.objects.create(
            addon=self.addon, body='review 2', user=user_factory(), rating=2
        )
        review1.update(created=self.days_ago(1))
        # Add a review belonging to a different add-on, a reply, a deleted
        # review and another older review by the same user as the first review.
        # They should not be present in the list.
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=review1.user, rating=3
        )
        review_deleted.delete()
        Rating.objects.create(
            addon=self.addon,
            body='reply to review 1',
            reply_to=review1,
            user=user_factory(),
        )
        Rating.objects.create(
            addon=addon_factory(),
            body='review other addon',
            user=user_factory(),
            rating=4,
        )
        older_review = Rating.objects.create(
            addon=self.addon,
            body='review same user/addon older',
            user=review1.user,
            rating=5,
        )
        # We change `created` manually after the actual creation, so we need to
        # force a full refresh of the denormalized fields, because this
        # normally only happens at creation time.
        older_review.update(created=self.days_ago(42))
        older_review.update_denormalized_fields()
        assert review1.reload().is_latest is True
        assert older_review.reload().is_latest is False
        addon_rating_aggregates(self.addon.id)

        params = {'addon': self.addon.pk}
        params.update(kwargs)
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 2
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == review2.pk
        assert data['results'][1]['id'] == review1.pk
        if 'show_permissions_for' not in kwargs:
            assert 'can_reply' not in data

        if 'show_grouped_ratings' not in kwargs:
            assert 'grouped_ratings' not in data

        if 'show_for' not in kwargs:
            assert 'flags' not in data['results'][0]
            assert 'flags' not in data['results'][1]

        return data

    def test_list_show_permission_for_anonymous(self):
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'show_permissions_for': 666}
        )
        assert response.status_code == 400
        assert response.data['detail'] == (
            'show_permissions_for parameter value should be equal to the user '
            'id of the authenticated user'
        )

    def test_list_show_permission_for_not_int(self):
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'show_permissions_for': 'nope'}
        )
        assert response.status_code == 400
        assert response.data['detail'] == (
            'show_permissions_for parameter value should be equal to the user '
            'id of the authenticated user'
        )

    def test_list_show_permission_for_not_right_user(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.get(
            self.url,
            {'addon': self.addon.pk, 'show_permissions_for': self.user.pk + 42},
        )
        assert response.status_code == 400
        assert response.data['detail'] == (
            'show_permissions_for parameter value should be equal to the user '
            'id of the authenticated user'
        )

    def test_list_show_permissions_for_without_addon(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.get(
            self.url, {'user': self.user.pk, 'show_permissions_for': self.user.pk}
        )
        assert response.status_code == 400
        assert response.data['detail'] == (
            'show_permissions_for parameter is only valid if the addon '
            'parameter is also present'
        )

    def test_list_can_reply(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        self.addon.addonuser_set.create(user=self.user, listed=False)
        data = self.test_list_addon(show_permissions_for=self.user.pk)
        assert data['can_reply'] is True

    def test_list_can_not_reply(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        data = self.test_list_addon(show_permissions_for=self.user.pk)
        assert data['can_reply'] is False

    def test_list_can_reply_field_absent_in_v3(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        self.url = reverse_ns('rating-list', api_version='v3')
        data = self.test_list_addon(show_permissions_for=self.user.pk)
        assert 'can_reply' not in data

    def test_list_addon_queries(self):
        version1 = self.addon.current_version
        version2 = version_factory(addon=self.addon)
        review1 = Rating.objects.create(
            addon=self.addon,
            body='review 1',
            user=user_factory(),
            rating=1,
            version=version1,
        )
        review2 = Rating.objects.create(
            addon=self.addon,
            body='review 2',
            user=user_factory(),
            rating=2,
            version=version2,
        )
        review3 = Rating.objects.create(
            addon=self.addon,
            body='review 3',
            user=user_factory(),
            rating=2,
            version=version1,
        )
        review2.update(created=self.days_ago(1))
        review1.update(created=self.days_ago(2))

        assert Rating.unfiltered.count() == 3

        with self.assertNumQueries(7):
            # 7 queries:
            # - Two for opening and releasing a savepoint. Those only happen in
            #   tests, because TransactionTestCase wraps things in atomic().
            # - One for the ratings count (pagination)
            # - One for the ratings themselves
            # - One for the replies (there aren't any, but we don't know
            #   that without making a query)
            # - One for the addon
            # - One for its translations
            response = self.client.get(
                self.url, {'addon': self.addon.pk, 'lang': 'en-US'}
            )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 3
        assert data['results']
        assert len(data['results']) == 3
        assert data['results'][0]['body'] == review3.body
        assert data['results'][0]['addon']['slug'] == self.addon.slug
        assert data['results'][1]['body'] == review2.body
        assert data['results'][1]['addon']['slug'] == self.addon.slug
        assert data['results'][2]['body'] == review1.body
        assert data['results'][2]['addon']['slug'] == self.addon.slug

    def test_list_addon_queries_with_replies(self):
        version1 = self.addon.current_version
        version2 = version_factory(addon=self.addon)
        review1 = Rating.objects.create(
            addon=self.addon,
            body='review 1',
            user=user_factory(),
            rating=1,
            version=version1,
        )
        review2 = Rating.objects.create(
            addon=self.addon,
            body='review 2',
            user=user_factory(),
            rating=2,
            version=version2,
        )
        review3 = Rating.objects.create(
            addon=self.addon,
            body='review 3',
            user=user_factory(),
            rating=2,
            version=version1,
        )
        review2.update(created=self.days_ago(1))
        review1.update(created=self.days_ago(2))
        reply1 = Rating.objects.create(
            addon=self.addon,
            body='reply to review 1',
            reply_to=review1,
            user=user_factory(),
        )
        reply2 = Rating.objects.create(
            addon=self.addon,
            body='reply to review 2',
            reply_to=review2,
            user=reply1.user,
        )

        assert Rating.unfiltered.count() == 5

        with self.assertNumQueries(7):
            # 7 queries:
            # - Two for opening and releasing a savepoint. Those only happen in
            #   tests, because TransactionTestCase wraps things in atomic().
            # - One for the ratings count
            # - One for the ratings
            # - One for the replies (using prefetch_related())
            # - One for the addon
            # - One for its translations
            response = self.client.get(
                self.url, {'addon': self.addon.pk, 'lang': 'en-US'}
            )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 3
        assert data['results']
        assert len(data['results']) == 3
        assert data['results'][0]['body'] == review3.body
        assert data['results'][0]['reply'] is None
        assert data['results'][0]['addon']['slug'] == self.addon.slug
        assert data['results'][1]['body'] == review2.body
        assert data['results'][1]['reply']['body'] == reply2.body
        assert data['results'][1]['addon']['slug'] == self.addon.slug
        assert data['results'][2]['body'] == review1.body
        assert data['results'][2]['reply']['body'] == reply1.body
        assert data['results'][2]['addon']['slug'] == self.addon.slug

    def test_list_addon_grouped_ratings(self):
        data = self.test_list_addon(show_grouped_ratings='true')
        assert data['grouped_ratings']['1'] == 1
        assert data['grouped_ratings']['2'] == 1
        assert data['grouped_ratings']['3'] == 0
        assert data['grouped_ratings']['4'] == 0
        assert data['grouped_ratings']['5'] == 0

    def test_list_addon_without_grouped_ratings(self):
        data = self.test_list_addon(show_grouped_ratings='false')
        assert 'grouped_ratings' not in data

    def test_list_addon_with_funky_grouped_ratings_param(self):
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'show_grouped_ratings': 'blah'}
        )
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data['detail'] == ('show_grouped_ratings parameter should be a boolean')

    def test_list_addon_unknown(self, **kwargs):
        params = {'addon': self.addon.pk + 42}
        params.update(kwargs)
        response = self.client.get(self.url, params)
        assert response.status_code == 404
        data = json.loads(force_str(response.content))
        return data

    def test_list_addon_grouped_ratings_unknown_addon_not_present(self):
        data = self.test_list_addon_unknown(show_grouped_ratings=1)
        assert 'grouped_ratings' not in data

    def test_list_addon_guid(self):
        self.test_list_addon(addon=self.addon.guid)

    def test_list_addon_slug(self):
        self.test_list_addon(addon=self.addon.slug)

    def test_list_with_empty_reviews(self):
        def create_review(body='review text', user=None):
            return Rating.objects.create(
                addon=self.addon, user=user or user_factory(), rating=3, body=body
            )

        self.user = user_factory()

        create_review()
        create_review()
        create_review(body=None)
        create_review(body=None)
        create_review(body=None, user=self.user)

        # Do show the reviews with no body by default
        response = self.client.get(self.url, {'addon': self.addon.pk})
        data = json.loads(force_str(response.content))
        assert data['count'] == 5 == len(data['results'])

        self.client.login_api(self.user)
        # Unless you filter them out
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'filter': 'without_empty_body'}
        )
        data = json.loads(force_str(response.content))
        assert data['count'] == 2 == len(data['results'])

        # And maybe you only want your own empty reviews
        response = self.client.get(
            self.url,
            {'addon': self.addon.pk, 'filter': 'without_empty_body,with_yours'},
        )
        data = json.loads(force_str(response.content))
        assert data['count'] == 3 == len(data['results'])

    def test_list_user(self, **kwargs):
        self.user = user_factory()
        review1 = Rating.objects.create(
            addon=self.addon, body='review 1', user=self.user
        )
        review2 = Rating.objects.create(
            addon=self.addon, body='review 2', user=self.user
        )
        review1.update(created=self.days_ago(1))
        review2.update(created=self.days_ago(2))
        # Add a review belonging to a different user, a reply and a deleted
        # review. The reply should show up since it's made by the right user,
        # but the rest should be ignored.
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=self.user
        )
        review_deleted.delete()
        other_review = Rating.objects.create(
            addon=addon_factory(), body='review from other user', user=user_factory()
        )
        reply = Rating.objects.create(
            addon=other_review.addon,
            body='reply to other user',
            reply_to=other_review,
            user=self.user,
        )
        Rating.objects.create(
            addon=addon_factory(status=amo.STATUS_NULL),
            body='addon not public',
            user=self.user,
        )
        Rating.objects.create(
            addon=addon_factory(status=amo.STATUS_APPROVED, disabled_by_user=True),
            body='addon invisble',
            user=self.user,
        )

        assert Rating.unfiltered.count() == 7

        params = {'user': self.user.pk}
        params.update(kwargs)
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 3
        assert data['results']
        assert len(data['results']) == 3
        assert data['results'][0]['id'] == reply.pk
        assert data['results'][1]['id'] == review1.pk
        assert data['results'][2]['id'] == review2.pk
        assert 'can_reply' not in data  # Not enough information to show this.
        return data

    def test_list_addon_and_user(self):
        self.user = user_factory()
        old_review = Rating.objects.create(
            addon=self.addon, body='old review', user=self.user
        )
        old_review.update(created=self.days_ago(42))
        recent_review = Rating.objects.create(
            addon=self.addon, body='recent review', user=self.user
        )
        # None of those extra reviews should show up.
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=self.user
        )
        review_deleted.delete()
        other_review = Rating.objects.create(
            addon=addon_factory(), body='review from other user', user=user_factory()
        )
        Rating.objects.create(
            addon=other_review.addon,
            body='reply to other user',
            reply_to=other_review,
            user=self.user,
        )  # right user, wrong addon.
        Rating.objects.create(
            addon=addon_factory(), body='review from other addon', user=self.user
        )

        assert Rating.unfiltered.count() == 6

        # Since we're filtering on both addon and user, only the most recent
        # review from self.user on self.addon should show up.
        params = {'addon': self.addon.pk, 'user': self.user.pk}
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 1
        assert data['results']
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == recent_review.pk

    def test_list_addon_and_version(self):
        self.user = user_factory()
        old_version = self.addon.current_version
        other_version = version_factory(addon=self.addon)
        old_review = Rating.objects.create(
            addon=self.addon, body='old review', user=self.user, version=old_version
        )
        old_review.update(created=self.days_ago(42))
        other_review_same_addon = Rating.objects.create(
            addon=self.addon,
            body='review from other user',
            user=user_factory(),
            version=old_version,
        )
        # None of those extra reviews should show up.
        recent_review = Rating.objects.create(
            addon=self.addon,
            body='recent review',
            user=self.user,
            version=other_version,
        )
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=self.user
        )
        review_deleted.delete()
        Rating.objects.create(
            addon=other_review_same_addon.addon,
            body='reply to other user',
            reply_to=other_review_same_addon,
            user=self.user,
        )
        Rating.objects.create(
            addon=addon_factory(), body='review from other addon', user=self.user
        )

        assert Rating.unfiltered.count() == 6
        old_review.reload()
        recent_review.reload()
        assert old_review.is_latest is False
        assert recent_review.is_latest is True

        # Since we're filtering on both addon and version, only the reviews
        # matching that version should show up.
        params = {'addon': self.addon.pk, 'version': old_version.pk}
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 2
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == other_review_same_addon.pk
        assert data['results'][1]['id'] == old_review.pk

    def test_list_user_and_version(self):
        self.user = user_factory()
        old_version = self.addon.current_version
        other_version = version_factory(addon=self.addon)
        old_review = Rating.objects.create(
            addon=self.addon, body='old review', user=self.user, version=old_version
        )
        old_review.update(created=self.days_ago(42))
        # None of those extra reviews should show up.
        other_review_same_addon = Rating.objects.create(
            addon=self.addon,
            body='review from other user',
            user=user_factory(),
            version=old_version,
        )
        recent_review = Rating.objects.create(
            addon=self.addon,
            body='recent review',
            user=self.user,
            version=other_version,
        )
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=self.user
        )
        review_deleted.delete()
        Rating.objects.create(
            addon=other_review_same_addon.addon,
            body='reply to other user',
            reply_to=other_review_same_addon,
            user=self.user,
        )
        Rating.objects.create(
            addon=addon_factory(), body='review from other addon', user=self.user
        )

        assert Rating.unfiltered.count() == 6
        old_review.reload()
        recent_review.reload()
        assert old_review.is_latest is False
        assert recent_review.is_latest is True

        # Since we're filtering on both user and version, only the review
        # matching that user and version should show up.
        params = {'user': self.user.pk, 'version': old_version.pk}
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 1
        assert data['results']
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == old_review.pk

    def test_list_user_and_addon_and_version(self):
        self.user = user_factory()
        old_version = self.addon.current_version
        other_version = version_factory(addon=self.addon)
        old_review = Rating.objects.create(
            addon=self.addon, body='old review', user=self.user, version=old_version
        )
        old_review.update(created=self.days_ago(42))
        # None of those extra reviews should show up.
        other_review_same_addon = Rating.objects.create(
            addon=self.addon,
            body='review from other user',
            user=user_factory(),
            version=old_version,
        )
        recent_review = Rating.objects.create(
            addon=self.addon,
            body='recent review',
            user=self.user,
            version=other_version,
        )
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=self.user
        )
        review_deleted.delete()
        Rating.objects.create(
            addon=other_review_same_addon.addon,
            body='reply to other user',
            reply_to=other_review_same_addon,
            user=self.user,
        )
        Rating.objects.create(
            addon=addon_factory(), body='review from other addon', user=self.user
        )

        assert Rating.unfiltered.count() == 6
        old_review.reload()
        recent_review.reload()
        assert old_review.is_latest is False
        assert recent_review.is_latest is True

        # Since we're filtering on both user and version, only the review
        # matching that addon, user and version should show up.
        params = {
            'addon': self.addon.pk,
            'user': self.user.pk,
            'version': old_version.pk,
        }
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 1
        assert data['results']
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == old_review.pk

    def test_list_addon_score_filter(self):
        rating_3a = Rating.objects.create(
            addon=self.addon, body='review 3a', user=user_factory(), rating=3
        )
        rating_3b = Rating.objects.create(
            addon=self.addon, body='review 3b', user=user_factory(), rating=3
        )
        rating_4 = Rating.objects.create(
            addon=self.addon, body='review 4', user=user_factory(), rating=4
        )
        # Throw in some other ratings with different scores
        Rating.objects.create(
            addon=self.addon, body='review 2', user=user_factory(), rating=2
        )
        Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory(), rating=1
        )

        response = self.client.get(self.url, {'addon': self.addon.pk, 'score': '3,4'})
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == len(data['results']) == 3
        assert data['results'][0]['id'] == rating_4.pk
        assert data['results'][1]['id'] == rating_3b.pk
        assert data['results'][2]['id'] == rating_3a.pk

        # and with just one score
        response = self.client.get(self.url, {'addon': self.addon.pk, 'score': '3'})
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == len(data['results']) == 2
        assert data['results'][0]['id'] == rating_3b.pk
        assert data['results'][1]['id'] == rating_3a.pk

    def test_list_addon_score_filter_invalid(self):
        response = self.client.get(self.url, {'addon': self.addon.pk, 'score': '3,foo'})
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data['detail'] == (
            'score parameter should be an integer or a list of integers '
            '(separated by a comma).'
        )

    def test_score_filter_ignored_for_v3(self):
        Rating.objects.create(
            addon=self.addon, body='review 2', user=user_factory(), rating=2
        )
        params = {'addon': self.addon.pk, 'score': '3,4'}

        # with a default (v4+) url first
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 0

        # But will be ignored in v3
        response = self.client.get(reverse_ns('rating-list', api_version='v3'), params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == len(data['results']) == 1

    def test_list_addon_exclude_ratings(self):
        excluded_review1 = Rating.objects.create(
            addon=self.addon, body='review excluded 1', user=user_factory(), rating=5
        )
        excluded_review2 = Rating.objects.create(
            addon=self.addon, body='review excluded 2', user=user_factory(), rating=4
        )
        excluded_param = ','.join(map(str, (excluded_review1.pk, excluded_review2.pk)))
        self.test_list_addon(exclude_ratings=excluded_param)

    def test_list_addon_exclude_ratings_single(self):
        excluded_review1 = Rating.objects.create(
            addon=self.addon, body='review excluded 1', user=user_factory(), rating=5
        )
        excluded_param = str(excluded_review1.pk)
        self.test_list_addon(exclude_ratings=excluded_param)

    def test_list_addon_exclude_ratings_invalid(self):
        params = {'addon': self.addon.pk, 'exclude_ratings': 'garbage,1'}
        response = self.client.get(self.url, params)
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data['detail'] == (
            'exclude_ratings parameter should be an '
            'integer or a list of integers (separated by a comma).'
        )

    def test_list_user_grouped_ratings_not_present(self):
        return
        data = self.test_list_user(show_grouped_ratings=1)
        assert 'grouped_ratings' not in data

    def test_list_no_addon_or_user_present(self):
        response = self.client.get(self.url)
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data['detail'] == 'Need an addon or user parameter'

    def test_list_show_flags_for_anonymous(self):
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'show_flags_for': 666}
        )
        assert response.status_code == 400
        assert response.data['detail'] == (
            'show_flags_for parameter value should be equal to the user '
            'id of the authenticated user'
        )

    def test_list_show_flags_for_not_int(self):
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'show_flags_for': 'nope'}
        )
        assert response.status_code == 400
        assert response.data['detail'] == (
            'show_flags_for parameter value should be equal to the user '
            'id of the authenticated user'
        )

    def test_list_show_flags_for_not_right_user(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'show_flags_for': self.user.pk + 42}
        )
        assert response.status_code == 400
        assert response.data['detail'] == (
            'show_flags_for parameter value should be equal to the user '
            'id of the authenticated user'
        )

    def test_list_rating_flags(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        rating1 = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory(), rating=2
        )
        rating0 = Rating.objects.create(
            addon=self.addon, body='review 0', user=user_factory(), rating=1
        )
        reply_to_0 = Rating.objects.create(
            addon=self.addon,
            body='reply to review 0',
            reply_to=rating0,
            user=user_factory(),
        )
        params = {'addon': self.addon.pk, 'show_flags_for': self.user.pk}

        # First, not flagged
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['results'][0]['flags'] == []
        assert data['results'][0]['reply']['flags'] == []
        assert data['results'][1]['flags'] == []

        # then add some RatingFlag - one for a rating, the other a reply
        RatingFlag.objects.create(
            rating=rating1, user=self.user, flag=RatingFlag.LANGUAGE
        )
        RatingFlag.objects.create(
            rating=reply_to_0, user=self.user, flag=RatingFlag.OTHER, note='foo'
        )

        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        rating0 = data['results'][0]
        rating1 = data['results'][1]
        assert 'flags' in rating0
        assert 'flags' in rating1
        assert 'flags' in rating0['reply']
        assert rating0['flags'] == []
        assert rating0['reply']['flags'] == [{'flag': RatingFlag.OTHER, 'note': 'foo'}]
        assert rating1['flags'] == [{'flag': RatingFlag.LANGUAGE, 'note': None}]

    def test_list_rating_flags_absent_in_v3(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        rating = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory(), rating=1
        )
        RatingFlag.objects.create(
            rating=rating, user=self.user, flag=RatingFlag.OTHER, note='foo'
        )
        params = {'addon': self.addon.pk, 'show_flags_for': self.user.pk}
        response = self.client.get(reverse_ns('rating-list', api_version='v3'), params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert 'flags' not in data['results'][0]

    def test_detail(self):
        review = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory()
        )
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': review.pk})

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['id'] == review.pk

    def test_detail_reply(self):
        review = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory()
        )
        reply = Rating.objects.create(
            addon=self.addon,
            body='reply to review',
            user=user_factory(),
            reply_to=review,
        )
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': reply.pk})

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['id'] == reply.pk

    def test_detail_deleted(self):
        review = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory()
        )
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': review.pk})
        review.delete()

        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_detail_deleted_reply(self):
        review = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory()
        )
        reply = Rating.objects.create(
            addon=self.addon,
            body='reply to review',
            user=user_factory(),
            reply_to=review,
        )
        reply.delete()
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': review.pk})

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['id'] == review.pk
        assert data['reply'] is None

    def test_detail_show_deleted_admin(self):
        self.user = user_factory()
        self.grant_permission(self.user, 'Addons:Edit')
        self.client.login_api(self.user)
        review = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory()
        )
        reply = Rating.objects.create(
            addon=self.addon,
            body='reply to review',
            user=user_factory(),
            reply_to=review,
        )
        reply.delete()
        review.delete()
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': review.pk})

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['id'] == review.pk
        assert data['reply']
        assert data['reply']['id'] == reply.pk

    def test_detail_show_flags_for_anonymous(self):
        rating = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory()
        )
        detail_url = reverse_ns(self.detail_url_name, kwargs={'pk': rating.pk})
        response = self.client.get(detail_url, {'show_flags_for': 666})
        assert response.status_code == 400
        assert response.data['detail'] == (
            'show_flags_for parameter value should be equal to the user '
            'id of the authenticated user'
        )

    def test_detail_show_flags_for_not_int(self):
        rating = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory()
        )
        detail_url = reverse_ns(self.detail_url_name, kwargs={'pk': rating.pk})
        response = self.client.get(detail_url, {'show_flags_for': 'nope'})
        assert response.status_code == 400
        assert response.data['detail'] == (
            'show_flags_for parameter value should be equal to the user '
            'id of the authenticated user'
        )

    def test_detail_show_flags_for_not_right_user(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        rating = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory()
        )
        detail_url = reverse_ns(self.detail_url_name, kwargs={'pk': rating.pk})
        response = self.client.get(detail_url, {'show_flags_for': self.user.pk + 42})
        assert response.status_code == 400
        assert response.data['detail'] == (
            'show_flags_for parameter value should be equal to the user '
            'id of the authenticated user'
        )

    def test_detail_rating_flags(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        rating = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory(), rating=2
        )

        detail_url = reverse_ns(self.detail_url_name, kwargs={'pk': rating.pk})
        params = {'show_flags_for': self.user.pk}

        # First, not flagged
        response = self.client.get(detail_url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['flags'] == []

        # then add some RatingFlag - one for a rating, the other a reply
        RatingFlag.objects.create(
            rating=rating, user=self.user, flag=RatingFlag.LANGUAGE
        )

        response = self.client.get(detail_url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert 'flags' in data
        assert data['flags'] == [{'flag': RatingFlag.LANGUAGE, 'note': None}]

    def test_detail_rating_flags_absent_in_v3(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        rating = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory(), rating=1
        )
        RatingFlag.objects.create(
            rating=rating, user=self.user, flag=RatingFlag.OTHER, note='foo'
        )
        detail_url = reverse_ns(
            self.detail_url_name, kwargs={'pk': rating.pk}, api_version='v3'
        )
        params = {'show_flags_for': self.user.pk}
        response = self.client.get(detail_url, params)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert 'flags' not in data

    def test_detail_addon_not_public(self):
        review = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory()
        )
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': review.pk})

        self.addon.update(status=amo.STATUS_NULL)
        response = self.client.get(self.url)
        assert response.status_code == 404

        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_list_by_admin_does_not_show_deleted_by_default(self):
        self.user = user_factory()
        self.grant_permission(self.user, 'Addons:Edit')
        self.client.login_api(self.user)
        review1 = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory()
        )
        review2 = Rating.objects.create(
            addon=self.addon, body='review 2', user=user_factory()
        )
        review1.update(created=self.days_ago(1))
        # Add a review belonging to a different add-on, a reply and a deleted
        # review. They should not be present in the list.
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=review1.user
        )
        review_deleted.delete()
        Rating.objects.create(
            addon=self.addon,
            body='reply to review 2',
            reply_to=review2,
            user=user_factory(),
        )
        Rating.objects.create(
            addon=addon_factory(), body='review other addon', user=review1.user
        )
        # Also add a deleted reply to the first review, it should not be shown.
        deleted_reply = Rating.objects.create(
            addon=self.addon,
            body='reply to review 1',
            reply_to=review1,
            user=user_factory(),
        )
        deleted_reply.delete()

        assert Rating.unfiltered.count() == 6

        response = self.client.get(self.url, {'addon': self.addon.pk})
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 2
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == review2.pk
        assert data['results'][0]['reply'] is not None
        assert data['results'][1]['id'] == review1.pk
        assert data['results'][1]['reply'] is None

    def test_list_admin_show_deleted_if_requested(self):
        self.user = user_factory()
        self.grant_permission(self.user, 'Addons:Edit')
        self.client.login_api(self.user)
        review1 = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory()
        )
        review2 = Rating.objects.create(
            addon=self.addon, body='review 2', user=user_factory()
        )
        review1.update(created=self.days_ago(1))
        # Add a review belonging to a different add-on, a reply and a deleted
        # review. The deleted review should be present, not the rest.
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=review1.user
        )
        review_deleted.update(created=self.days_ago(2))
        review_deleted.delete()
        Rating.objects.create(
            addon=self.addon,
            body='reply to review 2',
            reply_to=review2,
            user=user_factory(),
        )
        Rating.objects.create(
            addon=addon_factory(), body='review other addon', user=review1.user
        )
        # Also add a deleted reply to the first review, it should be shown
        # as a child of that review.
        deleted_reply = Rating.objects.create(
            addon=self.addon,
            body='reply to review 1',
            reply_to=review1,
            user=user_factory(),
        )
        deleted_reply.delete()

        assert Rating.unfiltered.count() == 6

        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'filter': 'with_deleted'}
        )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data['count'] == 3
        assert data['results']
        assert len(data['results']) == 3
        assert data['results'][0]['id'] == review2.pk
        assert data['results'][0]['reply'] is not None
        assert data['results'][1]['id'] == review1.pk
        assert data['results'][1]['reply'] is not None
        assert data['results'][1]['reply']['id'] == deleted_reply.pk
        assert data['results'][2]['id'] == review_deleted.pk

    def test_list_weird_parameters(self):
        self.addon.update(slug='my-slûg')
        user = user_factory()
        Rating.objects.create(addon=self.addon, body='A review.', user=user)

        # No user, but addon is present.
        response = self.client.get(self.url, {'addon': self.addon.pk, 'user': ''})
        assert response.status_code == 200

        # No addon, but user is present.
        response = self.client.get(self.url, {'addon': '', 'user': user.pk})
        assert response.status_code == 200

        # Addon parameter is utf-8.
        response = self.client.get(self.url, {'addon': 'my-slûg'})
        assert response.status_code == 200

        # User parameter is weird (it should be a pk, as string): 404.
        response = self.client.get(self.url, {'addon': self.addon.pk, 'user': 'çæ→'})
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data == {'detail': 'user parameter should be an integer.'}

        # Version parameter is weird (it should be a pk, as string): 404.
        response = self.client.get(self.url, {'addon': self.addon.pk, 'version': 'çæ→'})
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data == {'detail': 'version parameter should be an integer.'}

    def test_get_then_post_then_get_any_caching_is_cleared(self):
        """Make sure there is no overzealous caching going on when requesting
        the list of reviews for a given user+addon+version combination.
        Regression test for #5006."""
        self.user = user_factory()
        self.client.login_api(self.user)

        # Do a get filtering on both addon and user: it should not find
        # anything.
        response = self.client.get(
            self.url,
            {
                'addon': self.addon.pk,
                'version': self.addon.current_version.pk,
                'user': self.user.pk,
            },
        )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert len(data['results']) == 0
        assert data['count'] == 0

        # Do a post to add a review by this user.
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )

        assert response.status_code == 201

        # Re-do the same get as before, should now find something since the
        # view is avoiding count() caching in this case.
        response = self.client.get(
            self.url,
            {
                'addon': self.addon.pk,
                'version': self.addon.current_version.pk,
                'user': self.user.pk,
            },
        )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert len(data['results']) == 1
        assert data['count'] == 1

    def test_no_throttle(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory(), rating=1
        )

        # We should be able to get as quick as we want.
        response = self.client.get(self.url, {'addon': self.addon.pk})
        assert response.status_code == 200
        response = self.client.get(self.url, {'addon': self.addon.pk})
        assert response.status_code == 200


class TestRatingViewSetDelete(TestCase):
    client_class = APITestClientSessionID
    detail_url_name = 'rating-detail'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.user = user_factory()
        self.rating = Rating.objects.create(
            addon=self.addon,
            version=self.addon.current_version,
            rating=1,
            body='My review',
            user=self.user,
        )
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': self.rating.pk})

    def test_delete_anonymous(self):
        response = self.client.delete(self.url)
        assert response.status_code == 401

    def test_delete_no_rights(self):
        other_user = user_factory()
        self.client.login_api(other_user)
        response = self.client.delete(self.url)
        assert response.status_code == 403

    def test_delete_admin(self):
        admin_user = user_factory()
        self.grant_permission(admin_user, 'Addons:Edit')
        self.client.login_api(admin_user)
        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert Rating.objects.count() == 0
        assert Rating.unfiltered.count() == 1

    def test_delete_moderator_flagged(self):
        self.rating.update(editorreview=True)
        admin_user = user_factory()
        self.grant_permission(admin_user, 'Ratings:Moderate')
        self.client.login_api(admin_user)
        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert Rating.objects.count() == 0
        assert Rating.unfiltered.count() == 1

    def test_delete_moderator_not_flagged(self):
        admin_user = user_factory()
        self.grant_permission(admin_user, 'Ratings:Moderate')
        self.client.login_api(admin_user)
        response = self.client.delete(self.url)
        assert response.status_code == 403
        assert Rating.objects.count() == 1

    def test_delete_moderator_but_addon_author(self):
        admin_user = user_factory()
        self.addon.addonuser_set.create(user=admin_user)
        self.grant_permission(admin_user, 'Ratings:Moderate')
        self.client.login_api(admin_user)
        response = self.client.delete(self.url)
        assert response.status_code == 403
        assert Rating.objects.count() == 1

    def test_delete_owner(self):
        self.client.login_api(self.user)
        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert Rating.objects.count() == 0
        assert Rating.unfiltered.count() == 1

    def test_delete_owner_reply(self):
        addon_author = user_factory()
        self.addon.addonuser_set.create(user=addon_author)
        self.client.login_api(addon_author)
        reply = Rating.objects.create(
            addon=self.addon,
            reply_to=self.rating,
            body='Reply that will be delêted...',
            user=addon_author,
        )
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': reply.pk})

        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert Rating.objects.count() == 1
        assert Rating.unfiltered.count() == 2

    def test_delete_404(self):
        self.client.login_api(self.user)
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': self.rating.pk + 42})
        response = self.client.delete(self.url)
        assert response.status_code == 404
        assert Rating.objects.count() == 1

    @override_settings(CACHES=locmem_cache)
    def test_throttle(self):
        # Add ratings for different addons posted by the same user.
        rating_a = self.rating
        addon_b = addon_factory()
        rating_b = Rating.objects.create(
            addon=addon_b,
            version=addon_b.current_version,
            rating=2,
            body='Second Review to delete',
            user=self.user,
        )

        with freeze_time('2021-07-23') as frozen_time:
            # And confirm we can rapidly delete them.
            self.client.login_api(self.user)
            response = self.client.delete(
                reverse_ns(self.detail_url_name, kwargs={'pk': rating_a.pk})
            )
            assert response.status_code == 204
            response = self.client.delete(
                reverse_ns(self.detail_url_name, kwargs={'pk': rating_b.pk})
            )
            assert response.status_code == 204
            assert Rating.objects.count() == 0

            # Go over 5 requests and you get throttled though.
            for x in range(0, 3):
                response = self.client.delete(
                    reverse_ns(self.detail_url_name, kwargs={'pk': rating_b.pk})
                )
                # We'll get a 404 because the rating doesn't exist anymore,
                # but's that's irrelevant, throttling would be triggered
                # earlier.
                assert response.status_code == 404
            response = self.client.delete(
                reverse_ns(self.detail_url_name, kwargs={'pk': rating_b.pk})
            )
            assert response.status_code == 429

            # You're free after a minute.
            frozen_time.tick(delta=timedelta(minutes=1))
            addon_c = addon_factory()
            rating_c = Rating.objects.create(
                addon=addon_c,
                version=addon_c.current_version,
                rating=3,
                body='Third Review to delete',
                user=self.user,
            )
            response = self.client.delete(
                reverse_ns(self.detail_url_name, kwargs={'pk': rating_c.pk})
            )
            assert response.status_code == 204


class TestRatingViewSetEdit(TestCase):
    client_class = APITestClientSessionID
    detail_url_name = 'rating-detail'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.user = user_factory(username='areviewuser')
        self.rating = Rating.objects.create(
            addon=self.addon,
            version=self.addon.current_version,
            rating=1,
            body='My revïew',
            user=self.user,
        )
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': self.rating.pk})
        # add some denied words that won't match
        DeniedRatingWord.objects.create(word='something', moderation=True)
        DeniedRatingWord.objects.create(word='else', moderation=False)

    def test_edit_anonymous(self):
        response = self.client.patch(self.url, {'body': 'løl!'})
        assert response.status_code == 401

        response = self.client.put(self.url, {'body': 'løl!'})
        assert response.status_code == 405

    def test_edit_no_rights(self):
        other_user = user_factory()
        self.client.login_api(other_user)
        response = self.client.patch(self.url, {'body': 'løl!'})
        assert response.status_code == 403

        response = self.client.put(self.url, {'body': 'løl!'})
        assert response.status_code == 405

    def test_edit_no_rights_even_reviewer(self):
        # Only admins can edit a review they didn't write themselves.
        reviewer_user = user_factory()
        self.grant_permission(reviewer_user, 'Addons:Review')
        self.client.login_api(reviewer_user)
        response = self.client.patch(self.url, {'body': 'løl!'})
        assert response.status_code == 403

        response = self.client.put(self.url, {'body': 'løl!'})
        assert response.status_code == 405

    def test_edit_owner_partial(self):
        original_created_date = self.days_ago(1)
        self.rating.update(created=original_created_date)
        self.client.login_api(self.user)
        response = self.client.patch(self.url, {'score': 2, 'body': 'løl!'})
        assert response.status_code == 200
        self.rating.reload()
        assert response.data['id'] == self.rating.pk
        assert response.data['body'] == str(self.rating.body) == 'løl!'
        assert response.data['score'] == self.rating.rating == 2
        assert response.data['version'] == {
            'id': self.rating.version.id,
            'version': self.rating.version.version,
        }
        assert self.rating.created == original_created_date

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == self.user
        assert activity_log.arguments == [self.addon, self.rating]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert len(mail.outbox) == 0

    def test_edit_owner_put_not_allowed(self):
        self.client.login_api(self.user)
        response = self.client.put(self.url, {'body': 'løl!'})
        assert response.status_code == 405

    def test_edit_dont_allow_version_to_be_edited(self):
        self.client.login_api(self.user)
        new_version = version_factory(addon=self.addon)
        response = self.client.patch(self.url, {'version': new_version.pk})
        assert response.status_code == 400
        assert response.data['version'] == [
            "You can't change the version of the add-on reviewed once "
            'the review has been created.'
        ]

    def test_edit_dont_allow_addon_to_be_edited(self):
        self.client.login_api(self.user)
        new_addon = addon_factory()
        response = self.client.patch(self.url, {'addon': new_addon.pk})
        assert response.status_code == 400
        assert response.data['addon'] == [
            "You can't change the add-on of a review once it has been created."
        ]

    def test_edit_admin(self):
        original_review_user = self.rating.user
        admin_user = user_factory(username='mylittleadmin')
        self.grant_permission(admin_user, 'Addons:Edit')
        self.client.login_api(admin_user)
        response = self.client.patch(self.url, {'body': 'løl!'})
        assert response.status_code == 200
        self.rating.reload()
        assert response.data['id'] == self.rating.pk
        assert response.data['body'] == str(self.rating.body) == 'løl!'
        assert response.data['version'] == {
            'id': self.rating.version.id,
            'version': self.rating.version.version,
        }

        assert self.rating.user == original_review_user

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == admin_user
        assert activity_log.arguments == [self.addon, self.rating]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert len(mail.outbox) == 0

    def test_edit_reply(self):
        addon_author = user_factory()
        self.addon.addonuser_set.create(user=addon_author)
        self.client.login_api(addon_author)
        reply = Rating.objects.create(
            reply_to=self.rating,
            body='This is â reply',
            user=addon_author,
            addon=self.addon,
        )
        mail.outbox = []
        self.url = reverse_ns(self.detail_url_name, kwargs={'pk': reply.pk})

        response = self.client.patch(self.url, {'score': 5})
        assert response.status_code == 200
        # Since the review we're editing was a reply, rating' was an unknown
        # parameter and was ignored.
        reply.reload()
        assert reply.rating is None
        assert 'score' not in response.data

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == addon_author
        assert activity_log.arguments == [self.addon, reply]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert len(mail.outbox) == 0

    @override_settings(CACHES=locmem_cache)
    def test_throttle(self):
        self.client.login_api(self.user)

        with freeze_time('2021-07-23') as frozen_time:
            for x in range(1, 6):
                response = self.client.patch(
                    self.url, {'score': x, 'body': f'Blâh {x}'}
                )
                assert response.status_code == 200
                self.rating.reload()
                assert str(self.rating.body) == f'Blâh {x}'
                assert self.rating.rating == x

            # Over the limit now...
            response = self.client.patch(self.url, {'score': 1, 'body': 'Ooops'})
            assert response.status_code == 429
            self.rating.reload()
            assert str(self.rating.body) == 'Blâh 5'
            assert self.rating.rating == 5

            # Everything back to normal after waiting a minute.
            frozen_time.tick(delta=timedelta(minutes=1))
            response = self.client.patch(self.url, {'score': 1, 'body': 'I did it'})
            assert response.status_code == 200
            self.rating.reload()
            assert str(self.rating.body) == 'I did it'
            assert self.rating.rating == 1

    @override_settings(CACHES=locmem_cache)
    def test_no_throttling_with_relevant_permission(self):
        self.client.login_api(self.user)

        with freeze_time('2021-08-09') as frozen_time:
            for x in range(1, 6):
                response = self.client.patch(
                    self.url,
                    {'score': x, 'body': f'Blâh {x}'},
                    REMOTE_ADDR='127.0.0.42',
                    HTTP_X_FORWARDED_FOR=f'127.0.0.42, {get_random_ip()}',
                )
                assert response.status_code == 200
                self.rating.reload()
                assert str(self.rating.body) == f'Blâh {x}'
                assert self.rating.rating == x

            # Over the limit now...
            response = self.client.patch(
                self.url,
                {'score': 1, 'body': 'Ooops'},
                REMOTE_ADDR='127.0.0.42',
                HTTP_X_FORWARDED_FOR=f'127.0.0.42, {get_random_ip()}',
            )
            assert response.status_code == 429
            self.rating.reload()
            assert str(self.rating.body) == 'Blâh 5'
            assert self.rating.rating == 5

            # Now with the permission we should be ok.
            self.grant_permission(self.user, 'API:BypassThrottling')
            response = self.client.patch(
                self.url,
                {'score': 1, 'body': 'Eheheh'},
                REMOTE_ADDR='127.0.0.42',
                HTTP_X_FORWARDED_FOR=f'127.0.0.42, {get_random_ip()}',
            )
            assert response.status_code == 200
            self.rating.reload()
            assert str(self.rating.body) == 'Eheheh'
            assert self.rating.rating == 1

            # Someone else with the same IP would still be stuck.
            new_user = user_factory()
            new_rating = Rating.objects.create(
                addon=self.addon,
                version=self.addon.current_version,
                body='Another',
                rating=4,
                user=new_user,
            )
            new_url = reverse_ns(self.detail_url_name, kwargs={'pk': new_rating.pk})
            self.client.login_api(new_user)
            response = self.client.patch(
                new_url,
                {'score': 2, 'body': 'Ooops'},
                REMOTE_ADDR='127.0.0.42',
                HTTP_X_FORWARDED_FOR=f'127.0.0.42, {get_random_ip()}',
            )
            assert response.status_code == 429
            new_rating.reload()
            assert str(new_rating.body) == 'Another'
            assert new_rating.rating == 4

            # Everything back to normal after waiting a minute.
            frozen_time.tick(delta=timedelta(minutes=1))
            response = self.client.patch(
                new_url,
                {'score': 1, 'body': 'I did it'},
                REMOTE_ADDR='127.0.0.42',
                HTTP_X_FORWARDED_FOR=f'127.0.0.42, {get_random_ip()}',
            )
            assert response.status_code == 200
            new_rating.reload()
            assert str(new_rating.body) == 'I did it'
            assert new_rating.rating == 1

    @freeze_time(as_arg=True)
    def test_body_contains_banned_word_deny(frozen_time, self):
        DeniedRatingWord.objects.create(word='body', moderation=False)
        DeniedRatingWord.objects.create(word='foo', moderation=False)
        # This wouldn't be matched, because it's a moderate word instead.
        DeniedRatingWord.objects.create(word='test', moderation=True)
        self.client.login_api(self.user)
        response = self.client.patch(
            self.url,
            {
                'body': 'test bOdy_é',
                'score': 5,
            },
        )
        assert response.status_code == 400
        assert response.data == {
            'body': ['The review text cannot contain the word: "body"']
        }

        frozen_time.tick(delta=timedelta(minutes=1))
        response = self.client.patch(
            self.url,
            {
                'body': 'test bOdy-é FOO',
                'score': 5,
            },
        )
        assert response.status_code == 400
        assert response.data == {
            'body': ['The review text cannot contain any of the words: "body", "foo"']
        }
        assert not RatingFlag.objects.exists()

    def test_body_contains_banned_word_flag(self):
        user_factory(id=settings.TASK_USER_ID)
        DeniedRatingWord.objects.create(word='body', moderation=True)
        DeniedRatingWord.objects.create(word='wOrld', moderation=True)
        assert not self.rating.editorreview
        assert not self.rating.ratingflag_set.exists()
        self.client.login_api(self.user)

        response = self.client.patch(
            self.url,
            {
                'body': 'test bOdy_é',
                'score': 5,
            },
        )
        assert response.status_code == 200, response.json()
        self.rating.reload()
        assert self.rating.editorreview
        flag = self.rating.ratingflag_set.get()
        assert flag.flag == RatingFlag.AUTO_MATCH
        assert flag.note == 'Words matched: [body]'

        # And repeat with a different word
        response = self.client.patch(
            self.url,
            {
                'body': 'test bOdy-é WORld',
                'score': 5,
            },
        )
        assert response.status_code == 200, response.json()
        self.rating.reload()
        assert self.rating.editorreview
        flag = self.rating.ratingflag_set.get()  # still only one
        assert flag.flag == RatingFlag.AUTO_MATCH
        assert flag.note == 'Words matched: [body, world]'


class TestRatingViewSetPost(TestCase):
    client_class = APITestClientSessionID
    list_url_name = 'rating-list'
    detail_url_name = 'rating-detail'
    abuse_report_url_name = 'abusereportaddon-list'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.url = reverse_ns(self.list_url_name)
        # add some denied words that won't match
        DeniedRatingWord.objects.create(word='something', moderation=True)
        DeniedRatingWord.objects.create(word='else', moderation=False)

    def test_post_anonymous(self):
        response = self.client.post(
            self.url, {'addon': self.addon.pk, 'body': 'test bodyé', 'score': 5}
        )
        assert response.status_code == 401

    def test_post_no_addon(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'body': 'test bodyé',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data['addon'] == ['This field is required.']

    def test_post_no_version(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url, {'addon': self.addon.pk, 'body': 'test bodyé', 'score': 5}
        )
        assert response.status_code == 400
        assert response.data['version'] == ['This field is required.']

    def test_post_version_string(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 5,
                'version': self.addon.current_version.version,
            },
        )
        assert response.status_code == 400
        error_string = [
            ErrorDetail(
                string='Incorrect type. Expected pk value, received str.',
                code='incorrect_type',
            )
        ]
        assert response.data['version'] == error_string

    def test_post_body_too_long(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'x' * 4001,
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 400
        error_string = [
            ErrorDetail(
                string='Ensure this field has no more than 4000 characters.',
                code='max_length',
            )
        ]
        assert response.data['body'] == error_string

    def test_post_logged_in(self):
        addon_author = user_factory()
        self.addon.addonuser_set.create(user=addon_author)
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
            REMOTE_ADDR='213.225.31.25',
        )
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert str(review.body) == response.data['body'] == 'test bodyé'
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version,
        }
        assert 'ip_address' not in response.data
        assert review.ip_address == '213.225.31.25'
        assert not review.flag
        assert not review.editorreview

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == self.user
        assert activity_log.arguments == [self.addon, review]
        assert activity_log.action == amo.LOG.ADD_RATING.id
        assert activity_log.iplog.ip_address_binary == IPv4Address('213.225.31.25')

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [addon_author.email]

    def test_post_auto_flagged_and_cleaned(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        body = 'Trying to spam <br> http://éxample.com'
        cleaned_body = 'Trying to spam \n http://éxample.com'
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': body,
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert str(review.body) == response.data['body'] == cleaned_body
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version,
        }
        assert review.flag
        assert review.editorreview

    def test_post_rating_float(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 4.5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data['score'] == ['A valid integer is required.']

    def test_post_rating_too_big(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 6,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data['score'] == [
            'Ensure this value is less than or equal to 5.'
        ]

    def test_post_rating_too_low(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 0,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data['score'] == [
            'Ensure this value is greater than or equal to 1.'
        ]

    def test_post_rating_has_body(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert str(review.body) == response.data['body'] == 'test bodyé'
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version,
        }
        # and check it's not been auto flagged for moderation
        assert not review.editorreview
        assert not review.ratingflag_set.exists()

    def test_no_body_just_rating(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': None,
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert review.body is None
        assert response.data['body'] is None
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version,
        }

    def test_empty_body_just_rating(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': '',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert review.body == ''
        assert response.data['body'] == ''
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version,
        }

    def test_omit_body_completely_just_rating(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert review.body is None
        assert response.data['body'] is None
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version,
        }

    def test_post_rating_score_required(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data['score'] == ['This field is required.']

    def test_title_is_accepted_but_ignored(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'score': 5,
                'body': 'test bodyé',
                'title': 'ignore m£é€',
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert 'title' not in response.data

    def test_post_no_such_addon_id(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk + 42,
                'body': 'test body',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 404

    def test_post_version_not_linked_to_the_right_addon(self):
        addon2 = addon_factory()
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test body',
                'score': 5,
                'version': addon2.current_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data['version'] == [
            "This version of the add-on doesn't exist or isn't public."
        ]

    def test_post_deleted_addon(self):
        version_pk = self.addon.current_version.pk
        self.addon.delete()
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 5,
                'version': version_pk,
            },
        )
        assert response.status_code == 404

    def test_post_deleted_version(self):
        old_version_pk = self.addon.current_version.pk
        old_version = self.addon.current_version
        new_version = version_factory(addon=self.addon)
        old_version.delete()
        # Just in case, make sure the add-on is still public.
        self.addon.reload()
        assert self.addon.current_version == new_version
        assert self.addon.status

        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 5,
                'version': old_version_pk,
            },
        )
        assert response.status_code == 400
        assert response.data['version'] == [
            "This version of the add-on doesn't exist or isn't public."
        ]

    def test_post_disabled_version(self):
        self.addon.current_version.update(created=self.days_ago(1))
        old_version = self.addon.current_version
        new_version = version_factory(addon=self.addon)
        old_version.file.update(status=amo.STATUS_DISABLED)
        assert self.addon.current_version == new_version
        assert self.addon.status == amo.STATUS_APPROVED

        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 5,
                'version': old_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data['version'] == [
            "This version of the add-on doesn't exist or isn't public."
        ]

    def test_post_not_public_addon(self):
        version_pk = self.addon.current_version.pk
        self.addon.update(status=amo.STATUS_NULL)
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 5,
                'version': version_pk,
            },
        )
        assert response.status_code == 403

    def test_post_logged_in_but_is_addon_author(self):
        self.user = user_factory()
        self.addon.addonuser_set.create(user=self.user)
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bodyé',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data['non_field_errors'] == [
            "You can't leave a review on your own add-on."
        ]

    def test_post_twice_different_version(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        Rating.objects.create(
            addon=self.addon,
            version=self.addon.current_version,
            rating=1,
            body='My review',
            user=self.user,
        )
        second_version = version_factory(addon=self.addon)
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'My ôther review',
                'score': 2,
                'version': second_version.pk,
            },
        )
        assert response.status_code == 201
        assert Rating.objects.count() == 2

    def test_post_twice_same_version(self):
        # Posting a review more than once for the same version is not allowed.
        self.user = user_factory()
        self.client.login_api(self.user)
        Rating.objects.create(
            addon=self.addon,
            version=self.addon.current_version,
            rating=1,
            body='My review',
            user=self.user,
        )
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'My ôther review',
                'score': 2,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data['non_field_errors'] == [
            "You can't leave more than one review for the same version of " 'an add-on.'
        ]

    @override_settings(CACHES=locmem_cache)
    def test_throttle(self):
        with freeze_time('2017-11-01') as frozen_time:
            self.user = user_factory()
            self.client.login_api(self.user)
            # First post, no problem.
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview',
                    'score': 2,
                    'version': self.addon.current_version.pk,
                },
            )
            assert response.status_code == 201

            # Add version so to avoid the one rating per version restriction.
            new_version = version_factory(addon=self.addon)
            # Second post, nope, have to wait a while.
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My n3w réview',
                    'score': 2,
                    'version': new_version.pk,
                },
            )
            assert response.status_code == 429

            # Throttle is 1 minute so check we can go again
            frozen_time.tick(delta=timedelta(seconds=60))
            # And we're good.
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview',
                    'score': 2,
                    'version': new_version.pk,
                },
            )
            assert response.status_code == 201, response.content

            # Add fake actions to get close to the daily limit.
            for x in range(3, 23):
                self._add_fake_throttling_action(
                    view_class=RatingViewSet,
                    url=self.url,
                    user=self.user,
                    remote_addr=get_random_ip(),
                )
            # We should be able to post one more today.
            new_version = version_factory(addon=self.addon)
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview at the daily limit',
                    'score': 3,
                    'version': new_version.pk,
                },
            )
            assert response.status_code == 201

            # Over the daily limit now...
            new_version = version_factory(addon=self.addon)
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview over the daily limit',
                    'score': 4,
                    'version': new_version.pk,
                },
            )
            assert response.status_code == 429

            # Wait a day and we're good.
            new_version = version_factory(addon=self.addon)
            frozen_time.tick(delta=timedelta(hours=24, seconds=1))
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview should be fine now',
                    'score': 5,
                    'version': new_version.pk,
                },
            )
            assert response.status_code == 201

    @override_settings(CACHES=locmem_cache)
    def test_throttle_by_ip(self):
        with freeze_time('2017-11-01') as frozen_time:
            self.user = user_factory()
            self.client.login_api(self.user)
            # First post, no problem.
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview',
                    'score': 2,
                    'version': self.addon.current_version.pk,
                },
                REMOTE_ADDR='4.8.15.16',
                HTTP_X_FORWARDED_FOR=f'4.8.15.16, {get_random_ip()}',
            )
            assert response.status_code == 201

            # Add version so to avoid the one rating per version restriction.
            new_version = version_factory(addon=self.addon)
            # Second post, different user but same IP: nope, have to wait a
            # while.
            new_user = user_factory()
            self.client.login_api(new_user)
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My n3w réview',
                    'score': 2,
                    'version': new_version.pk,
                },
                REMOTE_ADDR='4.8.15.16',
                HTTP_X_FORWARDED_FOR=f'4.8.15.16, {get_random_ip()}',
            )
            assert response.status_code == 429

            # Throttle is 1 minute so check we can go again
            frozen_time.tick(delta=timedelta(seconds=60))
            # And we're good.
            self.client.login_api(self.user)
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview',
                    'score': 2,
                    'version': new_version.pk,
                },
                REMOTE_ADDR='4.8.15.16',
                HTTP_X_FORWARDED_FOR=f'4.8.15.16, {get_random_ip()}',
            )
            assert response.status_code == 201, response.content

            # Add fake actions to get close to the daily limit. Use the same IP
            # everytime, but with a different user (no need to save it into the
            # db) to avoid the per-user throttle.
            from olympia.users.models import UserProfile

            for x in range(3, 35):
                frozen_time.tick(delta=timedelta(seconds=61))
                self._add_fake_throttling_action(
                    view_class=RatingViewSet,
                    url=self.url,
                    user=UserProfile(pk=x),
                    remote_addr='4.8.15.16',
                )
            # We should be able to post one more today.
            new_version = version_factory(addon=self.addon)
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview at the daily limit',
                    'score': 3,
                    'version': new_version.pk,
                },
                REMOTE_ADDR='4.8.15.16',
                HTTP_X_FORWARDED_FOR=f'4.8.15.16, {get_random_ip()}',
            )
            assert response.status_code == 201

            # Over the daily limit for IPs now...
            new_version = version_factory(addon=self.addon)
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview over the daily limit',
                    'score': 4,
                    'version': new_version.pk,
                },
                REMOTE_ADDR='4.8.15.16',
                HTTP_X_FORWARDED_FOR=f'4.8.15.16, {get_random_ip()}',
            )
            assert response.status_code == 429

            # Wait a day and we're good.
            new_version = version_factory(addon=self.addon)
            frozen_time.tick(delta=timedelta(hours=24, seconds=1))
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview should be fine now',
                    'score': 5,
                    'version': new_version.pk,
                },
                REMOTE_ADDR='4.8.15.16',
                HTTP_X_FORWARDED_FOR=f'4.8.15.16, {get_random_ip()}',
            )
            assert response.status_code == 201

    @override_settings(CACHES=locmem_cache)
    def test_rating_post_throttle_separated_from_other_throttles(self):
        with freeze_time('2017-11-01') as frozen_time:
            self.user = user_factory()
            self.client.login_api(self.user)

            # Submit an abuse report
            report_abuse_url = reverse_ns(self.abuse_report_url_name)
            response = self.client.post(
                report_abuse_url,
                data={'addon': str(self.addon.pk), 'message': 'lol!'},
                REMOTE_ADDR='123.45.67.89',
                HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            )
            assert response.status_code == 201

            # Make sure you can still submit a rating after the abuse report.
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My n3w réview',
                    'score': 2,
                    'version': self.addon.current_version.pk,
                },
            )
            assert response.status_code == 201

            # Add version so to avoid the one rating per version restriction.
            new_version = version_factory(addon=self.addon)
            # Second post, nope, have to wait a while.
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My n3w réview',
                    'score': 2,
                    'version': new_version.pk,
                },
            )
            assert response.status_code == 429

            # We can still report abuse, it's a different throttle.
            response = self.client.post(
                report_abuse_url,
                data={'addon': str(self.addon.pk), 'message': 'again!'},
                REMOTE_ADDR='123.45.67.89',
                HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            )
            assert response.status_code == 201

            # We can still edit ratings (different throttle scope) as well.
            url = reverse_ns(
                self.detail_url_name, kwargs={'pk': Rating.objects.latest('pk').pk}
            )
            response = self.client.patch(url, {'score': 2, 'body': 'Edited Reviêw!'})
            assert response.status_code == 200

            # Throttle is 1 minute so check we can go again
            frozen_time.tick(delta=timedelta(seconds=60))

            # And we're good.
            response = self.client.post(
                self.url,
                {
                    'addon': self.addon.pk,
                    'body': 'My réview',
                    'score': 2,
                    'version': new_version.pk,
                },
            )
            assert response.status_code == 201, response.content

    @freeze_time(as_arg=True)
    def test_body_contains_banned_word_deny(frozen_time, self):
        DeniedRatingWord.objects.create(word='body', moderation=False)
        DeniedRatingWord.objects.create(word='foo', moderation=False)
        # This wouldn't be matched, because it's a moderate word instead.
        DeniedRatingWord.objects.create(word='test', moderation=True)
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bOdy_é',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data == {
            'body': ['The review text cannot contain the word: "body"']
        }

        frozen_time.tick(delta=timedelta(minutes=1))
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bOdy-é FOO',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 400
        assert response.data == {
            'body': ['The review text cannot contain any of the words: "body", "foo"']
        }
        assert not Rating.objects.exists()

    def test_body_contains_banned_word_flag(self):
        user_factory(id=settings.TASK_USER_ID)
        DeniedRatingWord.objects.create(word='body', moderation=True)
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bOdy,é',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 201
        assert Rating.objects.exists()
        rating = Rating.objects.get()
        assert rating.editorreview
        flag = rating.ratingflag_set.get()
        assert flag.flag == RatingFlag.AUTO_MATCH
        assert flag.note == 'Words matched: [body]'

    def test_user_restriction_deny_by_email(self):
        self.user = user_factory()
        EmailUserRestriction.objects.create(
            email_pattern=self.user.email,
            restriction_type=RESTRICTION_TYPES.RATING,
        )
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bOdyé',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 403
        assert response.data == {'detail': str(EmailUserRestriction.error_message)}
        assert not Rating.objects.exists()

    def test_user_restriction_deny_by_disposable_email(self):
        self.user = user_factory(email='foo@baa.com')
        DisposableEmailDomainRestriction.objects.create(
            domain='baa.com',
            restriction_type=RESTRICTION_TYPES.RATING,
        )
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bOdyé',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 403
        assert response.data == {
            'detail': str(DisposableEmailDomainRestriction.error_message)
        }
        assert not Rating.objects.exists()

    def test_user_restriction_deny_by_ip(self):
        self.user = user_factory()
        ip = '123.45.67.89'
        IPNetworkUserRestriction.objects.create(
            network=ip,
            restriction_type=RESTRICTION_TYPES.RATING,
        )
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            data={'addon': str(self.addon.pk), 'message': 'again!'},
            REMOTE_ADDR=ip,
            HTTP_X_FORWARDED_FOR=f'{ip}, {get_random_ip()}',
        )
        assert response.status_code == 403
        assert response.data == {'detail': str(IPNetworkUserRestriction.error_message)}
        assert not Rating.objects.exists()

    def test_user_restriction_flag_by_email(self):
        user_factory(id=settings.TASK_USER_ID)
        self.user = user_factory()
        EmailUserRestriction.objects.create(
            email_pattern=self.user.email,
            restriction_type=RESTRICTION_TYPES.RATING_MODERATE,
        )
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bOdyé',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 201
        assert Rating.objects.exists()
        rating = Rating.objects.get()
        assert rating.editorreview
        flag = rating.ratingflag_set.get()
        assert flag.flag == RatingFlag.AUTO_RESTRICTION
        assert flag.note == (
            f'{self.user.email} or {{127.0.0.1}} matched a UserRestriction'
        )

    def test_user_restriction_flag_by_disposable_email(self):
        user_factory(id=settings.TASK_USER_ID)
        self.user = user_factory(email='foo@baa.com')
        DisposableEmailDomainRestriction.objects.create(
            domain='baa.com',
            restriction_type=RESTRICTION_TYPES.RATING_MODERATE,
        )
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bOdyé',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
        )
        assert response.status_code == 201
        assert Rating.objects.exists()
        rating = Rating.objects.get()
        assert rating.editorreview
        flag = rating.ratingflag_set.get()
        assert flag.flag == RatingFlag.AUTO_RESTRICTION
        assert flag.note == (
            f'{self.user.email} or {{127.0.0.1}} matched a UserRestriction'
        )

    def test_user_restriction_flag_by_ip(self):
        user_factory(id=settings.TASK_USER_ID)
        self.user = user_factory()
        ip = '123.45.67.89'
        IPNetworkUserRestriction.objects.create(
            network=ip,
            restriction_type=RESTRICTION_TYPES.RATING_MODERATE,
        )
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(
            self.url,
            {
                'addon': self.addon.pk,
                'body': 'test bOdyé',
                'score': 5,
                'version': self.addon.current_version.pk,
            },
            REMOTE_ADDR=ip,
            HTTP_X_FORWARDED_FOR=f'{ip}, {get_random_ip()}',
        )
        assert response.status_code == 201
        assert Rating.objects.exists()
        rating = Rating.objects.get()
        assert rating.editorreview
        flag = rating.ratingflag_set.get()
        assert flag.flag == RatingFlag.AUTO_RESTRICTION
        assert flag.note == f'{self.user.email} or {{{ip}}} matched a UserRestriction'


class TestRatingViewSetFlag(TestCase):
    client_class = APITestClientSessionID
    flag_url_name = 'rating-flag'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.rating_user = user_factory()
        self.rating = Rating.objects.create(
            addon=self.addon,
            version=self.addon.current_version,
            rating=1,
            body='My review',
            user=self.rating_user,
        )
        self.url = reverse_ns(self.flag_url_name, kwargs={'pk': self.rating.pk})

    def test_url_v3(self):
        expected_url = '/v3/reviews/review/%d/flag/' % self.rating.pk
        v3_url = reverse_ns(
            'rating-flag', api_version='v3', kwargs={'pk': self.rating.pk}
        )
        assert v3_url.endswith(expected_url)

    def test_url_default(self):
        expected_url = '/v5/ratings/rating/%d/flag/' % self.rating.pk
        assert self.url.endswith(expected_url)

    def test_flag_anonymous(self):
        response = self.client.post(self.url)
        assert response.status_code == 401
        assert self.rating.reload().editorreview is False

    def test_flag_logged_in_no_flag_field(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(self.url)
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data['flag'] == ['This field is required.']
        assert self.rating.reload().editorreview is False

    def test_flag_logged_in(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(self.url, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 202
        data = json.loads(force_str(response.content))
        assert data['flag'] == 'review_flag_reason_spam'
        assert data['note'] == ''
        assert data['rating']['addon']['id'] == self.addon.id
        assert data['user']['id'] == self.user.id
        assert RatingFlag.objects.count() == 1
        flag = RatingFlag.objects.latest('pk')
        assert flag.flag == 'review_flag_reason_spam'
        assert flag.user == self.user
        assert flag.rating == self.rating
        assert self.rating.reload().editorreview is True

    def test_flag_logged_in_with_note(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(
            self.url,
            data={'flag': 'review_flag_reason_spam', 'note': 'This is my nøte.'},
        )
        assert response.status_code == 202
        assert RatingFlag.objects.count() == 1
        flag = RatingFlag.objects.latest('pk')
        # Flag was changed automatically since a note is being posted.
        assert flag.flag == 'review_flag_reason_other'
        assert flag.user == self.user
        assert flag.rating == self.rating
        assert flag.note == 'This is my nøte.'
        assert self.rating.reload().editorreview is True

    def test_flag_reason_other_without_notes_is_forbidden(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(self.url, data={'flag': 'review_flag_reason_other'})
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data['note'] == [
            'A short explanation must be provided when selecting "Other" as a'
            ' flag reason.'
        ]

    def test_flag_logged_in_unknown_flag_type(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(self.url, data={'flag': 'lol'})
        assert response.status_code == 400
        data = json.loads(force_str(response.content))
        assert data['flag'] == [
            'Invalid flag [lol] - must be one of [review_flag_reason_spam,'
            'review_flag_reason_language,review_flag_reason_bug_support,'
            'review_flag_reason_other]'
        ]
        assert self.rating.reload().editorreview is False

    def test_flag_logged_in_flag_already_exists(self):
        other_user = user_factory()
        other_flag = RatingFlag.objects.create(
            user=other_user, rating=self.rating, flag='review_flag_reason_language'
        )
        self.user = user_factory()
        flag = RatingFlag.objects.create(
            user=self.user, rating=self.rating, flag='review_flag_reason_other'
        )
        self.client.login_api(self.user)
        response = self.client.post(self.url, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 202
        # We should have re-used the existing flag posted by self.user, so the
        # count should still be 2.
        assert RatingFlag.objects.count() == 2
        flag.reload()
        # Flag was changed from other to spam.
        assert flag.flag == 'review_flag_reason_spam'
        assert flag.user == self.user
        assert flag.rating == self.rating
        # Other flag was untouched.
        other_flag.reload()
        assert other_flag.user == other_user
        assert other_flag.flag == 'review_flag_reason_language'
        assert other_flag.rating == self.rating
        assert self.rating.reload().editorreview is True

    def test_flag_logged_in_addon_denied(self):
        self.make_addon_unlisted(self.addon)
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(self.url, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 404
        assert self.rating.reload().editorreview is False

    def test_flag_logged_in_no_such_review(self):
        self.rating.delete()
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(self.url, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 404
        assert Rating.unfiltered.get(pk=self.rating.pk).editorreview is False

    def test_flag_logged_in_review_author(self):
        self.client.login_api(self.rating_user)
        response = self.client.post(self.url, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 403
        assert self.rating.reload().editorreview is False

    @override_settings(CACHES=locmem_cache)
    def test_throttle(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        # Create another addon for us to flag
        addon_b = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        rating_b = Rating.objects.create(
            addon=addon_b,
            version=addon_b.current_version,
            rating=2,
            body='My review',
            user=self.rating_user,
        )
        url_b = reverse_ns(self.flag_url_name, kwargs={'pk': rating_b.pk})

        with freeze_time('2021-07-23') as frozen_time:
            response = self.client.post(
                self.url, data={'flag': 'review_flag_reason_spam'}
            )
            assert response.status_code == 202
            response = self.client.post(url_b, data={'flag': 'review_flag_reason_spam'})
            assert response.status_code == 202
            # Both should have been flagged.
            assert RatingFlag.objects.count() == 2

            for x in range(0, 18):
                # You can keep flagging up to 20 a day.
                response = self.client.post(
                    url_b, data={'flag': 'review_flag_reason_spam'}
                )
                assert response.status_code == 202

            # Then it becomes too much.
            response = self.client.post(url_b, data={'flag': 'review_flag_reason_spam'})
            assert response.status_code == 429

            # Even waiting an hour doesn't let you continue.
            frozen_time.tick(delta=timedelta(hours=1))
            response = self.client.post(url_b, data={'flag': 'review_flag_reason_spam'})
            assert response.status_code == 429

            # Waiting 24 hours (total) does.
            frozen_time.tick(delta=timedelta(hours=23))
            response = self.client.post(url_b, data={'flag': 'review_flag_reason_spam'})
            assert response.status_code == 202


class TestRatingViewSetReply(TestCase):
    client_class = APITestClientSessionID
    reply_url_name = 'rating-reply'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.rating_user = user_factory()
        self.rating = Rating.objects.create(
            addon=self.addon,
            version=self.addon.current_version,
            rating=1,
            body='My review',
            user=self.rating_user,
        )
        self.url = reverse_ns(self.reply_url_name, kwargs={'pk': self.rating.pk})

    def test_url_v3(self):
        v3_url = reverse_ns(
            'rating-reply', api_version='v3', kwargs={'pk': self.rating.pk}
        )
        expected_url = '/api/v3/reviews/review/%d/reply/' % self.rating.pk
        assert v3_url.endswith(expected_url)

    def test_url_default(self):
        expected_url = '/api/v5/ratings/rating/%d/reply/' % self.rating.pk
        assert self.url.endswith(expected_url)

    def test_get_method_not_allowed(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        self.client.login_api(self.addon_author)
        response = self.client.get(self.url)
        assert response.status_code == 405

    def test_reply_anonymous(self):
        response = self.client.post(self.url, data={})
        assert response.status_code == 401

    def test_reply_non_addon_author(self):
        self.client.login_api(self.rating_user)
        response = self.client.post(self.url, data={})
        assert response.status_code == 403

    def test_reply_no_such_review(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        self.client.login_api(self.addon_author)
        self.url = reverse_ns(self.reply_url_name, kwargs={'pk': self.rating.pk + 42})
        response = self.client.post(self.url, data={})
        assert response.status_code == 404

    def test_reply_admin(self):
        ActivityLog.objects.all().delete()
        mail.outbox = []
        self.admin_user = user_factory()
        self.grant_permission(self.admin_user, 'Addons:Edit')
        self.client.login_api(self.admin_user)
        response = self.client.post(
            self.url,
            data={
                'body': 'My âdmin réply...',
            },
        )
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert review.body == response.data['body'] == 'My âdmin réply...'
        assert review.rating is None
        assert 'score' not in response.data
        assert review.user == self.admin_user
        assert review.reply_to == self.rating
        assert 'reply_to' not in response.data  # It's already in the URL...
        assert review.addon == self.addon
        assert review.version is None
        assert 'version' not in response.data

        assert ActivityLog.objects.exists()

        assert len(mail.outbox) == 1

    def test_reply(self):
        ActivityLog.objects.all().delete()
        mail.outbox = []
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        self.client.login_api(self.addon_author)
        response = self.client.post(
            self.url,
            data={
                'body': 'My réply...',
            },
        )
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert review.body == response.data['body'] == 'My réply...'
        assert review.rating is None
        assert 'score' not in response.data
        assert review.user == self.addon_author
        assert review.reply_to == self.rating
        assert 'reply_to' not in response.data  # It's already in the URL...
        assert review.addon == self.addon
        assert review.version is None
        assert 'version' not in response.data

        assert ActivityLog.objects.exists()

        assert len(mail.outbox) == 1

    def test_reply_if_a_reply_already_exists_updates_existing(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        existing_reply = Rating.objects.create(
            reply_to=self.rating,
            user=self.addon_author,
            addon=self.addon,
            body='My existing rêply',
        )
        self.client.login_api(self.addon_author)
        response = self.client.post(
            self.url,
            data={
                'body': 'My réply...',
            },
        )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert Rating.objects.count() == 2
        existing_reply.reload()
        assert str(existing_reply.body) == data['body'] == 'My réply...'

    def test_reply_if_an_existing_reply_was_deleted_updates_existing(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        existing_reply = Rating.objects.create(
            reply_to=self.rating,
            user=self.addon_author,
            addon=self.addon,
            body='My existing rêply',
        )
        existing_reply.delete()  # Soft delete the existing reply.
        assert Rating.objects.count() == 1
        assert Rating.unfiltered.count() == 2
        self.client.login_api(self.addon_author)
        response = self.client.post(
            self.url,
            data={
                'body': 'My réply...',
            },
        )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert Rating.objects.count() == 2  # No longer deleted.
        assert Rating.unfiltered.count() == 2
        existing_reply.reload()
        assert str(existing_reply.body) == data['body'] == 'My réply...'
        assert existing_reply.deleted is False

    def test_reply_disabled_addon(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        self.client.login_api(self.addon_author)
        self.addon.update(disabled_by_user=True)
        response = self.client.post(self.url, data={})
        assert response.status_code == 404

    def test_replying_to_a_reply_is_not_possible(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        self.client.login_api(self.addon_author)
        self.original_review = Rating.objects.create(
            addon=self.addon,
            version=self.addon.current_version,
            rating=1,
            body='My review',
            user=self.rating_user,
        )
        self.rating.update(
            user=self.addon_author, rating=None, reply_to=self.original_review
        )
        response = self.client.post(self.url, data={'body': 'LOL øø!'})
        assert response.status_code == 400
        assert response.data['non_field_errors'] == [
            "You can't reply to a review that is already a reply."
        ]

    @override_settings(CACHES=locmem_cache)
    def test_throttle(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        other_rating = Rating.objects.create(
            addon=self.addon,
            version=self.addon.current_version,
            rating=1,
            body='My review',
            user=user_factory(),
        )
        other_url = reverse_ns(self.reply_url_name, kwargs={'pk': other_rating.pk})

        with freeze_time('2017-11-01') as frozen_time:
            self.client.login_api(self.addon_author)
            # First post, no problem.
            response = self.client.post(
                self.url,
                data={
                    'body': 'My réply...',
                },
            )
            assert response.status_code == 201

            # Throttle is 1 per 5 seconds so after 4 seconds we have to wait
            frozen_time.tick(delta=timedelta(seconds=4))
            # Second post, nope, have to wait a while.
            response = self.client.post(
                other_url,
                data={
                    'body': 'Another réply',
                },
            )
            assert response.status_code == 429

            frozen_time.tick(delta=timedelta(seconds=5))
            # And we're good.
            response = self.client.post(
                other_url,
                data={
                    'body': 'Really réply!',
                },
            )
            assert response.status_code == 201
