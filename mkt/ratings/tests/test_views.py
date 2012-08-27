from nose.tools import eq_
from pyquery import PyQuery as pq

from access.models import Group, GroupUser
import amo
from amo.urlresolvers import reverse
import amo.tests
from reviews.models import Review, ReviewFlag
from stats.models import ClientData, Contribution
from users.models import UserProfile
from zadmin.models import DownloadSource

from mkt.developers.models import ActivityLog
from mkt.webapps.models import Installed, Webapp


class ReviewTest(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.dev = UserProfile.objects.get(pk=31337)
        self.admin = UserProfile.objects.get(username='admin')
        self.regular = UserProfile.objects.get(username='regularuser')
        # Fixtures blow chunks.
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

    def get_webapp(self):
        return Webapp.objects.get(id=337141)

    def log_in_dev(self):
        self.client.login(username=self.dev.email, password='password')

    def log_in_admin(self):
        self.client.login(username=self.admin.email, password='password')

    def log_in_regular(self):
        self.client.login(username=self.regular.email, password='password')

    def enable_waffle(self):
        self.create_switch(name='ratings')


class TestCreate(ReviewTest):

    def setUp(self):
        super(TestCreate, self).setUp()
        self.add = self.webapp.get_ratings_url('add')
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
        r = self.client.get(self.add)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'ratings/add.html')

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
            r = self.client.post(self.add, {'body': body})
            self.assertFormError(r, 'form', 'body', 'This field is required.')

    def test_no_rating(self):
        r = self.client.post(self.add, {'body': 'no rating'})
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

    def test_review_edit_review_initial(self):
        # Existing review? Then edit that review.
        r = self.client.get(self.add)
        eq_(pq(r.content)('textarea[name=body]').html(), 'I \u042f so hard.')

        # A reply is not a review.
        self.reply.user = self.user
        self.reply.save()
        r = self.client.get(self.add)
        eq_(pq(r.content)('textarea[name=body]').html(), 'I \u042f so hard.')

        # No review? Then do a new review.
        self.review.delete()
        r = self.client.get(self.add)
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
        self.enable_waffle()
        self.client.logout()
        r = self.client.get(self.detail)
        submit_button = pq(r.content)('#add-first-review')
        eq_(submit_button.length, 1)
        eq_(submit_button.text(), 'Submit a Review')

    def test_add_link_logged(self):
        # Ensure logged user can see Add Review links.
        self.enable_waffle()
        r = self.client.get(self.detail)
        doc = pq(r.content)('#review')
        eq_(doc('#add-first-review').length, 0)

    def test_add_link_dev(self):
        # Ensure developer cannot see Add Review links.
        self.enable_waffle()
        self.log_in_dev()
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_premium_no_add_review_link_visitor(self):
        # Check for no review link for premium apps for non-logged user.
        self.enable_waffle()
        self.client.logout()
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_premium_no_add_review_link_logged(self):
        self.enable_waffle()
        # Check for no review link for premium apps for logged users.
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_premium_add_review_link_dev(self):
        # Check for no review link for premium apps for app owners.
        self.enable_waffle()
        self.log_in_dev()
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_premium_no_add_review_link(self):
        # Check for review link for non-purchased premium apps.
        self.enable_waffle()
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_premium_add_review_link(self):
        # Check for review link for owners of purchased premium apps.
        self.enable_waffle()
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 1)

    def test_no_reviews_premium_no_add_review_link(self):
        # Ensure no 'Review this App' link for non-purchased premium apps.
        self.enable_waffle()
        Review.objects.all().delete()
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 0)

    def test_reviews_premium_add_review_link(self):
        # Ensure 'Review this App' link exists for purchased premium apps.
        self.enable_waffle()
        Review.objects.all().delete()
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 1)

    def test_reviews_premium_edit_review_link(self):
        # Ensure 'Review this App' link exists for purchased premium apps.
        self.enable_waffle()
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
        self.enable_waffle()
        Review.objects.all().delete()
        self.webapp.addonpurchase_set.create(user=self.user,
                                             type=amo.CONTRIB_REFUND)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 1)

    def test_add_review_premium_refunded(self):
        # Ensure able to add review for refunded premium apps.
        self.enable_waffle()
        Review.objects.all().delete()
        self.webapp.addonpurchase_set.create(user=self.user,
                                             type=amo.CONTRIB_REFUND)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.add)
        eq_(r.status_code, 200)

    def test_review_link_plural(self):
        # We have reviews.
        self.enable_waffle()
        self.webapp.update(total_reviews=2)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('.average-rating').text(),
            'Rated 4 out of 5 stars 2 reviews')

    def test_review_link_singular(self):
        # We have one review.
        self.enable_waffle()
        self.webapp.update(total_reviews=1)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('.average-rating').text(),
            'Rated 4 out of 5 stars 1 review')

    def test_support_link(self):
        # Test no link if no support url or contribution.
        self.enable_waffle()
        r = self.client.get(self.add)
        eq_(pq(r.content)('.support-link').length, 0)

        # Test support email if no support url.
        self.webapp.support_email = {'en-US': 'test@test.com'}
        self.webapp.save()
        r = self.client.get(self.add)
        doc = pq(r.content)('.support-link')
        eq_(doc.length, 1)

        # Test link to support url if support url.
        self.webapp.support_url = {'en-US': 'test'}
        self.webapp.save()
        r = self.client.get(self.add)
        doc = pq(r.content)('.support-link a')
        eq_(doc.length, 1)
        eq_(doc.attr('href'), 'test')

        # Test link to support flow if contribution.
        c = Contribution.objects.create(addon=self.webapp, user=self.user,
                                        type=amo.CONTRIB_PURCHASE)
        r = self.client.get(self.add)
        doc = pq(r.content)('.support-link a')
        eq_(doc.length, 1)
        eq_(doc.attr('href'), reverse('support', args=[c.id]))

    def test_not_rated(self):
        # We don't have any reviews, and I'm not allowed to submit a review.
        self.enable_waffle()
        Review.objects.all().delete()
        self.log_in_dev()
        r = self.client.get(self.detail)
        eq_(pq(r.content)('.not-rated').length, 1)

    def test_add_logged_out(self):
        self.client.logout()
        r = self.client.get(self.add)
        self.assertLoginRedirects(r, self.add, 302)

    def test_add_client_data(self):
        self.enable_waffle()
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
        self.enable_waffle()
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


class TestListing(ReviewTest):

    def setUp(self):
        super(TestListing, self).setUp()
        self.log_in_regular()
        self.listing = self.webapp.get_ratings_url('list')
        self.review_id = '#review-%s' % self.review.id
        self.reply_id = '#review-%s' % self.reply.id

    def test_items(self):
        r = self.client.get(self.listing)
        eq_(r.status_code, 200)
        doc = pq(r.content)
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

    def test_empty_list(self):
        Review.objects.all().delete()
        eq_(Review.objects.count(), 0)
        r = self.client.get(self.listing)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#reviews .item').length, 0)
        eq_(doc('#add-first-review').length, 1)

    def get_flags(self, actions):
        return sorted(c.get('class').replace(' post', '')
                      for c in actions.find('li:not(.hidden) a'))

    def test_actions_as_author(self):
        r = self.client.get(self.listing)
        reviews = pq(r.content)('#reviews')

        # My own review.
        eq_(self.get_flags(reviews.find(self.review_id + ' .actions')),
            ['delete', 'edit'])

        # A reply.
        eq_(self.get_flags(reviews.find(self.reply_id + ' .actions')),
            ['flag'])

    def test_actions_as_admin(self):
        self.log_in_admin()

        r = self.client.get(self.listing)
        reviews = pq(r.content)('#reviews')

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
