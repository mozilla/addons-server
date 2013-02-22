import mock
from nose.tools import eq_
from pyquery import PyQuery as pq


import amo
import amo.tests
from access.models import Group, GroupUser
from devhub.models import ActivityLog
from reviews.models import Review, ReviewFlag
from stats.models import ClientData
from users.models import UserProfile
from zadmin.models import DownloadSource

import mkt
from mkt.site.fixtures import fixture
from mkt.webapps.models import Installed, Webapp


class ReviewTest(amo.tests.TestCase):
    fixtures = ['base/users'] + fixture('webapp_337141', 'reviews')

    def setUp(self):
        self.webapp = self.get_webapp()
        self.dev = UserProfile.objects.get(pk=31337)
        self.admin = UserProfile.objects.get(username='admin')
        self.regular = UserProfile.objects.get(username='regularuser')
        self.review = Review.objects.get(pk=3)
        self.reply = Review.objects.get(pk=4)

    def get_webapp(self):
        return Webapp.objects.get(id=337141)

    def log_in_dev(self):
        self.client.login(username=self.dev.email, password='password')

    def log_in_admin(self):
        self.client.login(username=self.admin.email, password='password')

    def log_in_regular(self):
        self.client.login(username=self.regular.email, password='password')


class TestCreate(ReviewTest):

    def setUp(self):
        super(TestCreate, self).setUp()
        self.add = self.webapp.get_ratings_url('add')
        self.add_mobile = self.add + '?mobile=true'
        self.user = self.regular
        self.log_in_regular()
        self.detail = self.webapp.get_detail_url()

    def test_restrict(self):
        g = Group.objects.create(name='Restricted Users',
                                 rules='Restricted:UGC')
        GroupUser.objects.create(group=g, user=self.user)
        r = self.client.post(self.add, {'body': 'x', 'score': 1})
        self.assertEqual(r.status_code, 403)

    def test_add_logged(self):
        r = self.client.get(self.add_mobile)
        eq_(r.status_code, 200)

        self.assertTemplateUsed(r, 'ratings/add.html')
        assert pq(r.content)('title').text().startswith('Edit Your Review')

        # Desktop add review.
        r = self.client.get(self.add + '?mobile=false')
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'detail/app.html')

    def test_add_admin(self):
        self.log_in_admin()
        r = self.client.get(self.add)
        eq_(r.status_code, 200)

    def test_add_dev(self):
        self.log_in_dev()
        r = self.client.get(self.add)
        eq_(r.status_code, 403)

    def test_no_body(self):
        for body in ('', ' \t \n '):
            r = self.client.post(self.add_mobile, {'body': body})
            self.assertFormError(r, 'form', 'body', 'This field is required.')

    def test_no_rating(self):
        r = self.client.post(self.add_mobile, {'body': 'no rating'})
        self.assertFormError(r, 'form', 'rating', 'This field is required.')

    def test_body_has_url(self):
        """ test that both the create and revise reviews segments properly
            note reviews that contain URL like patterns for editorial review
        """
        for body in ['url http://example.com', 'address 127.0.0.1',
                     'url https://example.com/foo/bar', 'host example.org',
                     'quote example%2eorg', 'IDNA www.xn--ie7ccp.xxx']:
            self.client.post(self.add, {'body': body, 'rating': 2})
            ff = Review.objects.filter(addon=self.webapp)
            rf = ReviewFlag.objects.filter(review=ff[0])
            eq_(ff[0].flag, True)
            eq_(ff[0].editorreview, True)
            eq_(rf[0].note, 'URLs')
            rf.delete()
            # Clear the flags so we can test review revision flagging
            ff[0].flag = False
            ff[0].editorreview = False
            ff[0].save()

    def test_review_edit_review_initial(self):
        # Existing review? Then edit that review.
        r = self.client.get(self.add_mobile)
        eq_(pq(r.content)('textarea[name=body]').html(), 'I \u042f so hard.')

        # A reply is not a review.
        self.reply.user = self.user
        self.reply.save()
        r = self.client.get(self.add_mobile)
        eq_(pq(r.content)('textarea[name=body]').html(), 'I \u042f so hard.')

        # No review? Then do a new review.
        self.review.delete()
        r = self.client.get(self.add_mobile)
        eq_(pq(r.content)('textarea[name=body]').html(), None)

    def test_review_success_dup(self):
        Review.objects.create(
            body='This review already exists!',
            addon=self.webapp,
            user=self.user,
            ip_address='0.0.0.0')
        Review.objects.create(
            body='You bet it does!',
            addon=self.webapp,
            user=self.user,
            ip_address='0.0.0.0')
        r = self.client.post(self.add, {'body': 'xx', 'rating': 1})
        self.assertRedirects(r, self.webapp.get_ratings_url('list'),
                             status_code=302)
        # We're just testing for tracebacks. This should never happen in
        # production; we're handling it because there are reviews like this
        # on staging/dev.

    def test_review_reply_edit(self):
        self.log_in_dev()
        old_cnt = Review.objects.filter(reply_to__isnull=False).count()
        log_count = ActivityLog.objects.count()

        self.client.post(
            self.webapp.get_ratings_url('reply',
                                        args=[self.reply.reply_to_id]),
            {'body': 'revision'})
        eq_(Review.objects.filter(reply_to__isnull=False).count(), old_cnt)
        eq_(ActivityLog.objects.count(), log_count + 1,
            'Expected EDIT_REVIEW entry')

    def test_delete_reply(self):
        """Test that replies are deleted when reviews are edited."""
        self.log_in_regular()
        old_cnt = Review.objects.count()
        self.client.post(self.add, {'body': 'revision', 'rating': 2})
        eq_(Review.objects.count(), old_cnt - 1)

    def test_can_review_purchased(self):
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        data = {'body': 'x', 'rating': 1}
        eq_(self.client.get(self.add, data).status_code, 200)
        r = self.client.post(self.add, data)
        self.assertRedirects(r, self.webapp.get_ratings_url('list'),
                             status_code=302)

    def test_not_review_purchased(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        data = {'body': 'x', 'rating': 1}
        eq_(self.client.get(self.add, data).status_code, 403)
        eq_(self.client.post(self.add, data).status_code, 403)

    def test_add_link_visitor(self):
        # Ensure non-logged user can see Add Review links on detail page
        # but not on Reviews listing page.
        self.client.logout()
        r = self.client.get(self.detail)
        submit_button = pq(r.content)('#add-first-review')
        eq_(submit_button.length, 1)
        eq_(submit_button.text(), 'Write a Review')

    def test_edit_link_packaged(self):
        self.webapp.update(is_packaged=True)
        Review.objects.all().update(version=self.webapp.current_version)
        res = self.client.get(self.detail)
        submit_button = pq(res.content)('#add-first-review')
        eq_(submit_button.length, 1)
        eq_(submit_button.text(), 'Edit Your Review')

    def test_edit_link_packaged_new_version(self):
        self.webapp.update(is_packaged=True)
        amo.tests.version_factory(addon=self.webapp)
        self.webapp.update(_current_version=self.webapp.versions.latest())
        res = self.client.get(self.detail)
        submit_button = pq(res.content)('#add-first-review')
        eq_(submit_button.length, 1)
        eq_(submit_button.text(), 'Write a Review')

    def test_add_link_logged(self):
        # Ensure logged user can see Add Review links.
        r = self.client.get(self.detail)
        doc = pq(r.content)('#review')
        eq_(doc('#add-first-review').length, 0)

    def test_add_link_dev(self):
        # Ensure developer cannot see Add Review links.
        self.log_in_dev()
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_premium_no_add_review_link_visitor(self):
        # Check for no review link for premium apps for non-logged user.
        self.client.logout()
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_premium_no_add_review_link_logged(self):
        # Check for no review link for premium apps for logged users.
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_premium_add_review_link_dev(self):
        # Check for no review link for premium apps for app owners.
        self.log_in_dev()
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_premium_no_add_review_link(self):
        # Check for review link for non-purchased premium apps.
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_premium_add_review_link(self):
        # Check for review link for owners of purchased premium apps.
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 1)

    def test_no_reviews_premium_no_add_review_link(self):
        # Ensure no 'Review this App' link for non-purchased premium apps.
        Review.objects.all().delete()
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_reviews_premium_add_review_link(self):
        # Ensure 'Review this App' link exists for purchased premium apps.
        Review.objects.all().delete()
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 1)

    def test_reviews_premium_edit_review_link(self):
        # Ensure 'Review this App' link exists for purchased premium apps.
        Review.objects.create(
            rating=4,
            body={'ru': 'I \u042f so hard.'},
            addon=self.webapp,
            user=self.user,
            ip_address='63.245.213.8'
        )
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        submit_button = pq(r.content)('#add-first-review')
        eq_(submit_button.length, 1)
        eq_(submit_button.text(), 'Edit Your Review')

    def test_reviews_premium_refunded(self):
        # Ensure 'Review this App' link exists for refunded premium apps.
        Review.objects.all().delete()
        self.webapp.addonpurchase_set.create(user=self.user,
                                             type=amo.CONTRIB_REFUND)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 1)

    def test_add_review_premium_refunded(self):
        # Ensure able to add review for refunded premium apps.
        Review.objects.all().delete()
        self.webapp.addonpurchase_set.create(user=self.user,
                                             type=amo.CONTRIB_REFUND)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.add)
        eq_(r.status_code, 200)

    def test_not_rated(self):
        # We don't have any reviews, and I'm not allowed to submit a review.
        Review.objects.all().delete()
        self.log_in_dev()
        r = self.client.get(self.detail)
        eq_(pq(r.content)('.not-rated').length, 1)

    def test_add_logged_out(self):
        self.client.logout()
        r = self.client.get(self.add)
        self.assertLoginRedirects(r, self.add, 302)

    def test_add_client_data(self):
        client_data = ClientData.objects.create(
            download_source=DownloadSource.objects.create(name='mkt-test'),
            device_type='tablet', user_agent='test-agent', is_chromeless=False,
            language='pt-BR', region=3
        )
        client_data_diff_agent = ClientData.objects.create(
            download_source=DownloadSource.objects.create(name='mkt-test'),
            device_type='tablet', user_agent='test-agent2',
            is_chromeless=False, language='pt-BR', region=3
        )
        Installed.objects.create(user=self.user, addon=self.webapp,
                                 client_data=client_data)
        Installed.objects.create(user=self.user, addon=self.webapp,
                                 client_data=client_data_diff_agent)
        Review.objects.all().delete()

        self.client.post(self.add, {'body': 'x', 'rating': 4},
                         HTTP_USER_AGENT='test-agent')
        eq_(Review.objects.order_by('-created')[0].client_data, client_data)

    def test_add_client_data_no_user_agent_match(self):
        client_data = ClientData.objects.create(
            download_source=DownloadSource.objects.create(name='mkt-test'),
            device_type='tablet', user_agent='test-agent-1',
            is_chromeless=False, language='pt-BR', region=3
        )
        Installed.objects.create(user=self.user, addon=self.webapp,
                                 client_data=client_data)
        Review.objects.all().delete()

        self.client.post(self.add, {'body': 'x', 'rating': 4},
                         HTTP_USER_AGENT='test-agent-2')
        eq_(Review.objects.order_by('-created')[0].client_data, client_data)

    def test_review_success_edit(self):
        qs = self.webapp.reviews
        old_cnt = qs.count()
        log_count = ActivityLog.objects.count()

        r = self.client.post(self.add, {'body': 'xx', 'rating': 1})
        self.assertRedirects(r, self.webapp.get_ratings_url('list'),
                             status_code=302)
        eq_(qs.count(), old_cnt)
        eq_(ActivityLog.objects.count(), log_count + 1,
            'Expected EDIT_REVIEW entry')
        eq_(self.get_webapp().total_reviews, 1)
        eq_(Review.objects.all()[0].version, None)

    def test_review_success(self):
        Review.objects.all().delete()

        qs = self.webapp.reviews
        old_cnt = qs.count()
        log_count = ActivityLog.objects.count()

        r = self.client.post(self.add, {'body': 'xx', 'rating': 1})
        self.assertRedirects(r, self.webapp.get_ratings_url('list'),
                             status_code=302)
        eq_(qs.count(), old_cnt + 1)
        eq_(ActivityLog.objects.count(), log_count + 1,
            'Expected ADD_REVIEW entry')
        eq_(self.get_webapp().total_reviews, 1)
        eq_(Review.objects.all()[0].version, None)

    def test_packaged_app_review_success(self):
        self.webapp.update(is_packaged=True)

        Review.objects.all().delete()

        qs = self.webapp.reviews
        old_cnt = qs.count()
        log_count = ActivityLog.objects.count()

        r = self.client.post(self.add, {'body': 'xx', 'rating': 1})
        self.assertRedirects(r, self.webapp.get_ratings_url('list'),
                             status_code=302)
        eq_(qs.count(), old_cnt + 1)
        eq_(ActivityLog.objects.count(), log_count + 1,
            'Expected ADD_REVIEW entry')
        eq_(self.get_webapp().total_reviews, 1)
        eq_(Review.objects.all()[0].version, self.webapp.current_version)

    def test_packaged_app_review_success_edit(self):
        self.webapp.update(is_packaged=True)
        Review.objects.all().update(version=self.webapp.current_version)

        qs = self.webapp.reviews
        old_cnt = qs.count()
        log_count = ActivityLog.objects.count()

        r = self.client.post(self.add, {'body': 'xx', 'rating': 1})
        self.assertRedirects(r, self.webapp.get_ratings_url('list'),
                             status_code=302)
        eq_(qs.count(), old_cnt)
        eq_(ActivityLog.objects.count(), log_count + 1,
            'Expected EDIT_REVIEW entry')
        eq_(self.get_webapp().total_reviews, 1)
        eq_(Review.objects.all()[0].version, self.webapp.current_version)

    def test_packaged_app_review_next_version(self):
        self.webapp.update(is_packaged=True)
        old_version = self.webapp.current_version
        Review.objects.all().update(version=old_version)

        # Add a new version.
        amo.tests.version_factory(addon=self.webapp)
        self.webapp.update(_current_version=self.webapp.versions.latest())
        assert not self.get_webapp().current_version == old_version, (
            u'Expected versions to be different.')

        # Test adding a review on this new version.
        qs = self.webapp.reviews
        old_cnt = qs.count()
        log_count = ActivityLog.objects.count()

        r = self.client.post(self.add, {'body': 'xx', 'rating': 1})
        self.assertRedirects(r, self.webapp.get_ratings_url('list'),
                             status_code=302)
        eq_(qs.count(), old_cnt + 1)
        eq_(ActivityLog.objects.count(), log_count + 1,
            'Expected EDIT_REVIEW entry')
        eq_(self.get_webapp().total_reviews, 1)
        eq_(Review.objects.valid().filter(is_latest=True)[0].version,
            self.webapp.current_version)


class SlowTestCreate(ReviewTest):
    def setUp(self):
        #Block creation of mock for addon_review_aggregates.
        self.ara_mock = None
        super(SlowTestCreate, self).setUp()
        self.add = self.webapp.get_ratings_url('add')
        self.add_mobile = self.add + '?mobile=true'
        self.user = self.regular
        self.log_in_regular()
        self.detail = self.webapp.get_detail_url()
        self.review = Review.objects.create(
            rating=4,
            body={'ru': 'I \u042f so hard.'},
            addon=self.webapp,
            user=self.regular,
            ip_address='63.245.213.8'
        )
        self.reply = Review.objects.create(
            reply_to=self.review,
            body='Swag surfing and \u0434\u0430\u0432\u043d.',
            addon=self.webapp,
            user=self.dev,
            ip_address='0.0.0.0',
        )

    def test_review_link_plural(self):
        # We have reviews.
        self.webapp.update(total_reviews=2)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('.average-rating').text(),
            '2 reviews Rated 4 out of 5 stars')

    def test_review_link_singular(self):
        # We have one review.
        self.webapp.update(total_reviews=1)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('.average-rating').text(),
            '1 review Rated 4 out of 5 stars')


class TestListing(ReviewTest):

    def setUp(self):
        super(TestListing, self).setUp()
        self.log_in_regular()
        self.listing = self.webapp.get_ratings_url('list')
        self.detail = self.webapp.get_detail_url()
        self.review_id = '#review-%s' % self.review.id
        self.reply_id = '#review-%s' % self.reply.id

    def test_items(self):
        r = self.client.get(self.listing)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#add-review').length, 1)

        reviews = doc('#reviews .review')
        eq_(Review.objects.count(), 2)
        eq_(reviews.length, Review.objects.count())
        eq_(doc('.no-rating').length, 0)
        eq_(doc('.review-heading-profile').length, 0)

        # A review.
        item = reviews.filter('#review-%s' % self.review.id)
        eq_(item.hasClass('reply'), False)
        eq_(item.length, 1)
        eq_(item.attr('data-rating'), str(self.review.rating))

        # A reply.
        item = reviews.filter('#review-%s' % self.reply.id)
        eq_(item.length, 1)
        eq_(item.hasClass('reply'), True)
        eq_(self.reply.rating, None)
        eq_(item.attr('data-rating'), '')

    def test_version_in_byline_packaged(self):
        self.webapp.update(is_packaged=True)
        review = Review.objects.get(addon=self.webapp, user=self.regular)
        review.update(version=self.webapp.current_version)

        new_ver = amo.tests.version_factory(addon=self.webapp)
        self.webapp.update(_current_version=new_ver)

        res = self.client.get(self.listing)
        eq_(res.status_code, 200)
        byline = pq(res.content)('#review-%s span.byline' % review.id)
        assert 'for previous version' in byline.text(), (
            'Expected review for previous version note.')

    def test_empty_list(self):
        Review.objects.all().delete()
        eq_(Review.objects.count(), 0)
        r = self.client.get(self.listing)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#add-review').length, 1)
        eq_(doc('#reviews .item').length, 0)
        eq_(doc('#add-first-review').length, 1)

    def get_flags(self, actions):
        return sorted(c.get('class').replace(' post', '')
                      for c in actions.find('li:not(.hidden) a'))

    def test_actions_as_review_author(self):
        r = self.client.get(self.listing)
        doc = pq(r.content)
        reviews = doc('#reviews')

        eq_(doc('#add-review').length, 1,
            'App authors should be able to add reviews.')

        # My own review.
        eq_(self.get_flags(reviews.find(self.review_id + ' .actions')),
            ['delete', 'edit'])

        # A reply.
        eq_(self.get_flags(reviews.find(self.reply_id + ' .actions')),
            ['flag'])

    def test_actions_as_app_author(self):
        self.log_in_dev()
        r = self.client.get(self.listing)
        doc = pq(r.content)
        reviews = doc('#reviews')

        eq_(doc('#add-review').length, 0,
            'Authors should not be able add reviews.')

        # Someone's review.
        eq_(self.get_flags(reviews.find(self.review_id + ' .actions')),
            ['flag'])

        # My developer reply.
        eq_(self.get_flags(reviews.find(self.reply_id + ' .actions')),
            ['delete', 'edit'])

    def test_actions_as_admin(self):
        self.log_in_admin()

        r = self.client.get(self.listing)
        doc = pq(r.content)
        reviews = doc('#reviews')

        eq_(doc('#add-review').length, 1,
            'Admins should be able to add reviews.')

        eq_(self.get_flags(reviews.find(self.review_id + ' .actions')),
            ['delete', 'flag'])

        eq_(self.get_flags(reviews.find(self.reply_id + ' .actions')),
            ['delete', 'flag'])

    def test_actions_as_admin_and_author(self):
        self.log_in_admin()

        # Now I own the reply.
        self.reply.user = self.admin
        self.reply.save()

        r = self.client.get(self.listing)
        reviews = pq(r.content)('#reviews')

        eq_(self.get_flags(reviews.find(self.review_id + ' .actions')),
            ['delete', 'flag'])

        eq_(self.get_flags(reviews.find(self.reply_id + ' .actions')),
            ['delete', 'edit'])

    @mock.patch.object(mkt.regions.US, 'adolescent', False)
    def test_detail_local_reviews_only(self):
        client_data1 = ClientData.objects.create(
            download_source=DownloadSource.objects.create(name='mkt-test'),
            device_type='tablet', user_agent='test-agent', is_chromeless=False,
            language='pt-BR', region=3
        )
        client_data2 = ClientData.objects.create(
            download_source=DownloadSource.objects.create(name='mkt-test'),
            device_type='tablet', user_agent='test-agent', is_chromeless=False,
            language='en-US', region=2
        )

        Review.objects.create(
            rating=3,
            body={'ru': 'I \u042f a bit.'},
            addon=self.webapp,
            user=self.admin,
            client_data=client_data1,
            ip_address='127.0.0.2'
        )
        Review.objects.create(
            rating=4,
            body={'ru': 'I \u042f so hard.'},
            addon=self.webapp,
            user=self.regular,
            client_data=client_data2,
            ip_address='127.0.0.1'
        )
        for region in mkt.regions.REGIONS_DICT:
            r = self.client.get(self.detail, data={'region': region})
            eq_(r.status_code, 200)
            doc = pq(r.content)
            detail_reviews = doc('#reviews-detail .review-inner')

            r2 = self.client.get(self.listing, data={'region': region})
            eq_(r2.status_code, 200)
            listing_reviews = pq(r2.content)('#review-list > li.review')
            if region == 'us':
                eq_(listing_reviews.length, 1)
                eq_(detail_reviews.length, 1)
            else:
                eq_(listing_reviews.length, 2)
                eq_(detail_reviews.length, 2)


class TestFlag(ReviewTest):

    def setUp(self):
        super(TestFlag, self).setUp()
        self.log_in_regular()
        self.flag = self.webapp.get_ratings_url('flag', [self.reply.id])

    def test_no_login(self):
        self.client.logout()
        response = self.client.post(self.flag)
        eq_(response.status_code, 401)

    def test_new_flag(self):
        response = self.client.post(self.flag, {'flag': ReviewFlag.SPAM})
        eq_(response.status_code, 200)
        eq_(response.content, '{"msg": "Thanks; this review has been '
                              'flagged for editor approval."}')
        eq_(ReviewFlag.objects.filter(flag=ReviewFlag.SPAM).count(), 1)
        eq_(Review.objects.filter(editorreview=True).count(), 1)
