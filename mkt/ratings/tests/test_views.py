from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
import waffle

from users.models import UserProfile

from mkt.developers.models import ActivityLog
from mkt.ratings.models import Rating
from mkt.webapps.models import Webapp


class ReviewTest(amo.tests.TestCase):
    fixtures = ['base/admin', 'base/apps', 'ratings/dev-reply']

    def setUp(self):
        self.webapp = self.get_webapp()

    def get_webapp(self):
        return Webapp.objects.get(id=1865)

    def log_in_dev(self):
        self.client.login(username='trev@adblockplus.org', password='password')

    def log_in_admin(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')

    def make_it_my_review(self, review_id=218468):
        r = Rating.objects.get(id=review_id)
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
        self.assertFormError(r, 'form', 'score', 'This field is required.')

    def test_review_success(self):
        qs = Rating.objects.filter(addon=1865)
        old_cnt = qs.count()
        log_count = ActivityLog.objects.count()

        r = self.client.post(self.add, {'body': 'xx', 'score': 1})
        self.assertRedirects(r, self.webapp.get_detail_url() + '#reviews',
                             status_code=302)
        eq_(qs.count(), old_cnt + 1)
        eq_(ActivityLog.objects.count(), log_count + 1,
            'Expected ADD_REVIEW entry')
        eq_(self.get_webapp()._rating_counts,
            {'total': 1, 'positive': 1, 'negative': 0})

    def test_can_review_purchased(self):
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        data = {'body': 'x', 'score': 1}
        eq_(self.client.get(self.add, data).status_code, 200)
        r = self.client.post(self.add, data)
        self.assertRedirects(r, self.detail + '#reviews')

    def test_not_review_purchased(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        data = {'body': 'x', 'score': 1}
        eq_(self.client.get(self.add, data).status_code, 403)
        eq_(self.client.post(self.add, data).status_code, 403)

    def test_add_link_visitor(self):
        # Ensure non-logged user can see Add Review links on detail page
        # but not on Reviews listing page.
        self.enable_waffle()
        self.client.logout()
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#submit-review').length, 1)

    def test_add_link_logged(self):
        """Ensure logged user can see Add Review links."""
        self.enable_waffle()
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#submit-review').length, 1)

    def test_add_link_dev(self):
        # Ensure developer cannot see Add Review links.
        self.enable_waffle()
        self.log_in_dev()
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#submit-review').length, 0)

    def test_premium_no_add_review_link_visitor(self):
        # Check for no review link for premium apps for non-logged user.
        self.enable_waffle()
        self.client.logout()
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#submit-review').length, 0)

    def test_premium_no_add_review_link_logged(self):
        self.enable_waffle()
        # Check for no review link for premium apps for logged users.
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#submit-review').length, 0)

    def test_premium_add_review_link_dev(self):
        # Check for no review link for premium apps for app owners.
        self.enable_waffle()
        self.log_in_dev()
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#submit-review').length, 0)

    def test_premium_no_add_review_link(self):
        # Check for review link for non-purchased premium apps.
        self.enable_waffle()
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#submit-review').length, 0)

    def test_premium_add_review_link(self):
        # Check for review link for owners of purchased premium apps.
        self.enable_waffle()
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#submit-review').length, 1)

    def test_no_reviews_premium_no_add_review_link(self):
        # Ensure no 'Review this App' link for non-purchased premium apps.
        self.enable_waffle()
        Rating.objects.all().delete()
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#submit-review').length, 0)

    def test_no_reviews_premium_add_review_link(self):
        # Ensure 'Review this App' link exists for purchased premium apps.
        self.enable_waffle()
        Rating.objects.all().delete()
        self.webapp.addonpurchase_set.create(user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get(self.detail)
        eq_(pq(r.content)('#submit-review').length, 1)

    def test_add_logged_out(self):
        self.client.logout()
        r = self.client.get(self.add)
        self.assertLoginRedirects(r, self.add, 302)
