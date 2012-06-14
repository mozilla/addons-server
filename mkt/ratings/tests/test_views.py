from nose.tools import eq_
from pyquery import PyQuery as pq

import waffle

from access.models import Group, GroupUser
from addons.models import Addon
import amo
from amo.helpers import numberfmt
import amo.tests
from reviews.models import Review
from users.models import UserProfile

from mkt.developers.models import ActivityLog
from mkt.webapps.models import Webapp

class ReviewTest(amo.tests.TestCase):
    fixtures = ['base/admin', 'base/apps', 'reviews/dev-reply']

    def setUp(self):
        self.webapp = self.get_webapp()

    def get_webapp(self):
        # Because django hates my new fixture.
        addon = Addon.objects.get(id=1865)
        if not addon.is_webapp():
            addon.update(type=amo.ADDON_WEBAPP)
        return Webapp.objects.get(id=1865)

    def log_in_dev(self):
        self.client.login(username='trev@adblockplus.org', password='password')

    def log_in_admin(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')

    def make_it_my_review(self, review_id=218468):
        r = Review.objects.get(id=review_id)
        r.user = UserProfile.objects.get(username='jbalogh')
        r.save()

    def enable_waffle(self):
        waffle.models.Switch.objects.create(name='ratings', active=True)


class TestCreate(ReviewTest):

    def setUp(self):
        super(TestCreate, self).setUp()
        self.add = self.webapp.get_ratings_url('add')
        self.user = UserProfile.objects.get(email='root_x@ukr.net')
        assert self.client.login(username=self.user.email, password='password')
        self.detail = self.webapp.get_detail_url()

    def test_restrict(self):
        g = Group.objects.get(rules='Restricted:UGC')
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

    def test_review_success(self):
        qs = Review.objects.filter(addon=1865)
        old_cnt = qs.count()
        log_count = ActivityLog.objects.count()

        r = self.client.post(self.add, {'body': 'xx', 'rating': 1})
        self.assertRedirects(r, self.webapp.get_ratings_url('list'),
                             status_code=302)
        eq_(qs.count(), old_cnt + 1)
        eq_(ActivityLog.objects.count(), log_count + 1,
            'Expected ADD_REVIEW entry')
        eq_(self.get_webapp().total_reviews, 1)

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
        eq_(pq(r.content)('#add-first-review').length, 1)

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

    def test_no_reviews_premium_add_review_link(self):
        # Ensure 'Review this App' link exists for purchased premium apps.
        self.enable_waffle()
        Review.objects.all().delete()
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#add-first-review').length, 1)

    def test_review_link(self):
        # We have reviews.
        self.enable_waffle()
        r = self.client.get(self.detail)
        rating = int(round(self.webapp.average_rating))
        total = numberfmt(self.webapp.total_reviews)
        eq_(pq(r.content)('.average-rating').text(),
            'Rated %s out of 5 stars %s reviews' % (rating, total))

    def test_review_link_singular(self):
        # We have one review.
        self.enable_waffle()
        self.webapp.update(total_reviews=1)
        r = self.client.get(self.detail)
        rating = int(round(self.webapp.average_rating))
        eq_(pq(r.content)('.average-rating').text(),
            'Rated %s out of 5 stars 1 review' % rating)

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


class TestListing(ReviewTest):

    def setUp(self):
        super(TestListing, self).setUp()
        self.user = UserProfile.objects.get(email='root_x@ukr.net')
        assert self.client.login(username=self.user.email, password='password')
        self.listing = self.webapp.get_ratings_url('list')

    def test_items(self):
        r = self.client.get(self.listing)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        reviews = doc('#reviews .review')
        eq_(Review.objects.count(), 2)
        eq_(reviews.length, Review.objects.count())
        eq_(doc('.average-rating').length, 1)
        eq_(doc('.no-rating').length, 0)

        # A review.
        r = Review.objects.get(id=218207)
        item = reviews.filter('#review-218207')
        eq_(r.reply_to_id, None)
        eq_(item.hasClass('reply'), False)
        eq_(item.length, 1)
        eq_(item.attr('data-rating'), str(r.rating))

        # A reply.
        r = Review.objects.get(id=218468)
        item = reviews.filter('#review-218468')
        eq_(item.length, 1)
        eq_(r.reply_to_id, 218207)
        eq_(item.hasClass('reply'), True)
        eq_(r.rating, None)
        eq_(item.attr('data-rating'), '')

    def test_empty_list(self):
        Review.objects.all().delete()
        eq_(Review.objects.count(), 0)
        r = self.client.get(self.listing)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#reviews .item').length, 0)
        eq_(doc('#add-first-review').length, 1)
        eq_(doc('.average-rating.no-rating').length, 1)

    def get_flags(self, actions):
        return sorted(c.get('class').replace(' post', '')
                      for c in actions.find('li a'))

    def test_actions_as_author(self):
        r = self.client.get(self.listing)
        reviews = pq(r.content)('#reviews')

        # My own review.
        eq_(self.get_flags(reviews.find('#review-218207 .actions')),
            ['delete', 'edit'])

        # A reply.
        eq_(self.get_flags(reviews.find('#review-218468 .actions')), ['flag'])

    def test_actions_as_admin(self):
        assert self.client.login(username='jbalogh@mozilla.com',
                                 password='password')

        r = self.client.get(self.listing)
        reviews = pq(r.content)('#reviews')

        eq_(self.get_flags(reviews.find('#review-218207 .actions')),
            ['delete', 'flag'])

        eq_(self.get_flags(reviews.find('#review-218468 .actions')),
            ['delete', 'flag'])

    def test_actions_as_admin_and_author(self):
        assert self.client.login(username='jbalogh@mozilla.com',
                                 password='password')

        # Now I own the reply.
        self.make_it_my_review()

        r = self.client.get(self.listing)
        reviews = pq(r.content)('#reviews')

        eq_(self.get_flags(reviews.find('#review-218207 .actions')),
            ['delete', 'flag'])

        eq_(self.get_flags(reviews.find('#review-218468 .actions')),
            ['delete', 'edit'])
