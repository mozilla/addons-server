from django.core import mail

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse
from access.models import GroupUser
from addons.models import Addon
from addons.tests.test_views import TestMobile
from devhub.models import ActivityLog
from reviews.models import Review, ReviewFlag
from users.models import UserProfile

class ReviewTest(amo.tests.TestCase):
    fixtures = ['base/apps', 'reviews/dev-reply.json', 'base/admin']

    def login_dev(self):
        self.client.login(username='trev@adblockplus.org', password='password')

    def make_it_my_review(self, review_id=218468):
        r = Review.objects.get(id=review_id)
        r.user = UserProfile.objects.get(username='jbalogh')
        r.save()


class TestViews(ReviewTest):

    def test_dev_reply(self):
        url = reverse('reviews.detail', args=['a1865', 218468])
        r = self.client.get(url)
        eq_(r.status_code, 200)

    def test_404_user_page(self):
        url = reverse('reviews.user', args=['a1865', 233452342])
        r = self.client.get(url)
        eq_(r.status_code, 404)

    def test_feed(self):
        url = reverse('reviews.list.rss', args=['a1865'])
        r = self.client.get(url)
        eq_(r.status_code, 200)

    def test_list(self):
        r = self.client.get(reverse('i_reviews.list', args=['a1865']))
        eq_(r.status_code, 200)
        reviews = pq(r.content)('#reviews .item')
        eq_(reviews.length, Review.objects.count())
        eq_(reviews.find('.item-actions').length, 0)

        r = Review.objects.get(id=218207)
        item = reviews.filter('#review-218207')
        eq_(r.reply_to_id, None)
        eq_(item.hasClass('reply'), False)
        eq_(item.length, 1)
        eq_(item.attr('data-rating'), str(r.rating))

        r = Review.objects.get(id=218468)
        item = reviews.filter('#review-218468')
        eq_(item.length, 1)
        eq_(r.reply_to_id, 218207)
        eq_(item.hasClass('reply'), True)
        eq_(r.rating, None)
        eq_(item.attr('data-rating'), '')

    def test_list_item_actions(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        self.make_it_my_review()
        r = self.client.get(reverse('i_reviews.list', args=['a1865']))
        reviews = pq(r.content)('#reviews .item')

        r = Review.objects.get(id=218207)
        item = reviews.filter('#review-218207')
        actions = item.find('.item-actions')
        eq_(actions.length, 1)
        classes = sorted([c.get('class') for c in actions.find('li a')])
        eq_(classes, ['delete-review', 'flag-review'])

        r = Review.objects.get(id=218468)
        item = reviews.filter('#review-218468')
        actions = item.find('.item-actions')
        eq_(actions.length, 1)
        classes = sorted([c.get('class') for c in actions.find('li a')])
        eq_(classes, ['delete-review', 'review-edit'])


class TestFlag(ReviewTest):

    def setUp(self):
        self.url = reverse('reviews.flag', args=['a1865', 218468])
        self.client.login(username='jbalogh@mozilla.com', password='password')

    def test_no_login(self):
        self.client.logout()
        response = self.client.post(self.url)
        eq_(response.status_code, 401)

    def test_new_flag(self):
        response = self.client.post(self.url, {'flag': ReviewFlag.SPAM})
        eq_(response.status_code, 200)
        eq_(response.content, '{"msg": "Thanks; this review has been '
                                       'flagged for editor approval."}')
        eq_(ReviewFlag.objects.filter(flag=ReviewFlag.SPAM).count(), 1)
        eq_(Review.objects.filter(editorreview=True).count(), 1)

    def test_new_flag_mine(self):
        self.make_it_my_review()
        response = self.client.post(self.url, {'flag': ReviewFlag.SPAM})
        eq_(response.status_code, 404)

    def test_update_flag(self):
        response = self.client.post(self.url, {'flag': ReviewFlag.SPAM})
        eq_(response.status_code, 200)
        eq_(ReviewFlag.objects.filter(flag=ReviewFlag.SPAM).count(), 1)
        eq_(Review.objects.filter(editorreview=True).count(), 1)

        response = self.client.post(self.url, {'flag': ReviewFlag.LANGUAGE})
        eq_(response.status_code, 200)
        eq_(ReviewFlag.objects.filter(flag=ReviewFlag.LANGUAGE).count(), 1)
        eq_(ReviewFlag.objects.count(), 1)
        eq_(Review.objects.filter(editorreview=True).count(), 1)

    def test_flag_with_note(self):
        response = self.client.post(self.url,
                                    {'flag': ReviewFlag.OTHER, 'note': 'xxx'})
        eq_(response.status_code, 200)
        eq_(ReviewFlag.objects.filter(flag=ReviewFlag.OTHER).count(),
            1)
        eq_(ReviewFlag.objects.count(), 1)
        eq_(ReviewFlag.objects.get(flag=ReviewFlag.OTHER).note, 'xxx')
        eq_(Review.objects.filter(editorreview=True).count(), 1)

    def test_bad_flag(self):
        response = self.client.post(self.url, {'flag': 'xxx'})
        eq_(response.status_code, 400)
        eq_(Review.objects.filter(editorreview=True).count(), 0)


class TestDelete(ReviewTest):

    def setUp(self):
        self.url = reverse('reviews.delete', args=['a1865', 218207])
        self.client.login(username='jbalogh@mozilla.com', password='password')

    def test_no_login(self):
        self.client.logout()
        response = self.client.post(self.url)
        eq_(response.status_code, 401)

    def test_no_perms(self):
        GroupUser.objects.all().delete()
        response = self.client.post(self.url)
        eq_(response.status_code, 403)

    def test_404(self):
        url = reverse('reviews.delete', args=['a1865', 0])
        response = self.client.post(url)
        eq_(response.status_code, 404)

    def test_delete_review_with_dev_reply(self):
        cnt = Review.objects.count()
        response = self.client.post(self.url)
        eq_(response.status_code, 200)
        # Two are gone since we deleted a review with a reply.
        eq_(Review.objects.count(), cnt - 2)

    def test_delete_success(self):
        Review.objects.update(reply_to=None)
        cnt = Review.objects.count()
        response = self.client.post(self.url)
        eq_(response.status_code, 200)
        eq_(Review.objects.count(), cnt - 1)


class TestCreate(ReviewTest):

    def setUp(self):
        self.addon = Addon.objects.get(slug='a1865')
        self.add = reverse('reviews.add', args=[self.addon.slug])
        self.client.login(username='root_x@ukr.net', password='password')
        self.user = UserProfile.objects.get(email='root_x@ukr.net')
        self.qs = Review.objects.filter(addon=1865)
        self.log_count = ActivityLog.objects.count
        self.more = reverse('addons.detail_more', args=['a1865'])
        self.list = reverse('i_reviews.list', args=['a1865'])

    def test_no_body(self):
        r = self.client.post(self.add, {'body': ''})
        self.assertFormError(r, 'form', 'body', 'This field is required.')
        eq_(len(mail.outbox), 0)

    def test_no_rating(self):
        r = self.client.post(self.add, {'body': 'no rating'})
        self.assertFormError(r, 'form', 'rating', 'This field is required.')
        eq_(len(mail.outbox), 0)

    def test_review_success(self):
        old_cnt = self.qs.count()
        log_count = self.log_count()
        r = self.client.post(self.add, {'body': 'xx', 'rating': 3})
        self.assertRedirects(r, reverse('reviews.list', args=['a1865']),
                             status_code=302)
        eq_(self.qs.count(), old_cnt + 1)
        # We should have an ADD_REVIEW entry now.
        eq_(self.log_count(), log_count + 1)

        eq_(len(mail.outbox), 1)

        assert '3 out of 5' in mail.outbox[0].body, "Rating not included"
        self.assertTemplateUsed(r, 'reviews/emails/add_review.ltxt')

    def test_new_reply(self):
        self.login_dev()
        Review.objects.filter(reply_to__isnull=False).delete()
        url = reverse('reviews.reply', args=['a1865', 218207])
        r = self.client.post(url, {'body': 'unst unst'})
        self.assertRedirects(r,
                             reverse('reviews.detail', args=['a1865', 218207]))
        eq_(self.qs.filter(reply_to=218207).count(), 1)

        eq_(len(mail.outbox), 1)
        self.assertTemplateUsed(r, 'reviews/emails/reply_review.ltxt')

    def test_double_reply(self):
        self.login_dev()
        url = reverse('reviews.reply', args=['a1865', 218207])
        r = self.client.post(url, {'body': 'unst unst'})
        self.assertRedirects(r,
                             reverse('reviews.detail', args=['a1865', 218207]))
        eq_(self.qs.filter(reply_to=218207).count(), 1)
        review = Review.objects.get(id=218468)
        eq_('%s' % review.body, 'unst unst')

    def test_can_review_purchased(self):
        self.addon.addonpurchase_set.create(user=self.user)
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        data = {'body': 'x', 'rating': 1}
        eq_(self.client.get(self.add, data).status_code, 200)
        eq_(self.client.post(self.add, data).status_code, 302)

    def test_not_review_purchased(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        data = {'body': 'x', 'rating': 1}
        eq_(self.client.get(self.add, data).status_code, 403)
        eq_(self.client.post(self.add, data).status_code, 403)

    def test_add_link_visitor(self):
        """
        Ensure non-logged user can see Add Review links on details page
        but not on Reviews listing page.
        """
        self.client.logout()
        r = self.client.get_ajax(self.more)
        eq_(pq(r.content)('#add-review').length, 1)
        r = self.client.get(reverse('i_reviews.list', args=['a1865']))
        doc = pq(r.content)
        eq_(doc('#add-review').length, 0)
        eq_(doc('#add-first-review').length, 0)

    def test_add_link_logged(self):
        """Ensure logged user can see Add Review links."""
        r = self.client.get_ajax(self.more)
        eq_(pq(r.content)('#add-review').length, 1)
        r = self.client.get(self.list)
        doc = pq(r.content)
        eq_(doc('#add-review').length, 1)
        eq_(doc('#add-first-review').length, 0)

    def test_add_link_dev(self):
        """Ensure developer cannot see Add Review links."""
        self.login_dev()
        r = self.client.get_ajax(self.more)
        eq_(pq(r.content)('#add-review').length, 0)
        r = self.client.get(reverse('i_reviews.list', args=['a1865']))
        doc = pq(r.content)
        eq_(doc('#add-review').length, 0)
        eq_(doc('#add-first-review').length, 0)

    def test_list_none_add_review_link_visitor(self):
        """If no reviews, ensure visitor user cannot see Add Review link."""
        Review.objects.all().delete()
        self.client.logout()
        r = self.client.get(self.list)
        doc = pq(r.content)('#reviews')
        eq_(doc('#add-review').length, 0)
        eq_(doc('#no-add-first-review').length, 0)
        eq_(doc('#add-first-review').length, 1)

    def test_list_none_add_review_link_logged(self):
        """If no reviews, ensure logged user can see Add Review link."""
        Review.objects.all().delete()
        r = self.client.get(self.list)
        doc = pq(r.content)
        eq_(doc('#add-review').length, 1)
        eq_(doc('#no-add-first-review').length, 0)
        eq_(doc('#add-first-review').length, 1)

    def test_list_none_add_review_link_dev(self):
        """If no reviews, ensure developer can see Add Review link."""
        Review.objects.all().delete()
        self.login_dev()
        r = self.client.get(self.list)
        doc = pq(r.content)('#reviews')
        eq_(doc('#add-review').length, 0)
        eq_(doc('#no-add-first-review').length, 1)
        eq_(doc('#add-first-review').length, 0)

    def test_premium_no_add_review_link_visitor(self):
        """Check for no review link for premium add-ons for non-logged user."""
        self.client.logout()
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get_ajax(self.more)
        eq_(pq(r.content)('#add-review').length, 0)
        r = self.client.get(self.list)
        eq_(pq(r.content)('#add-review').length, 0)

    def test_premium_no_add_review_link_logged(self):
        """Check for no review link for premium add-ons for logged users."""
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get_ajax(self.more)
        eq_(pq(r.content)('#add-review').length, 0)
        r = self.client.get(self.list)
        eq_(pq(r.content)('#add-review').length, 0)

    def test_premium_add_review_link_dev(self):
        """Check for no review link for premium add-ons for add-on owners."""
        self.login_dev()
        self.addon.addonpurchase_set.create(user=self.user)
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get_ajax(self.more)
        eq_(pq(r.content)('#add-review').length, 0)
        r = self.client.get(self.list)
        eq_(pq(r.content)('#add-review').length, 0)

    def test_premium_add_review_link_nonpurchased_premium(self):
        """Check for review link for non-purchased premium add-ons."""
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get_ajax(self.more)
        eq_(pq(r.content)('#add-review').length, 0)
        r = self.client.get(self.list)
        eq_(pq(r.content)('#add-review').length, 0)

    def test_premium_add_review_link_purchased_premium(self):
        """Check for review link for owners of purchased premium add-ons."""
        self.addon.addonpurchase_set.create(user=self.user)
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        r = self.client.get_ajax(self.more)
        eq_(pq(r.content)('#add-review').length, 1)
        r = self.client.get(self.list)
        eq_(pq(r.content)('#add-review').length, 1)


class TestEdit(ReviewTest):

    def setUp(self):
        self.client.login(username='root_x@ukr.net', password='password')

    def test_edit(self):
        url = reverse('reviews.edit', args=['a1865', 218207])
        r = self.client.post(url, {'rating': 2, 'body': 'woo woo'},
                             X_REQUESTED_WITH='XMLHttpRequest')
        eq_(r.status_code, 200)
        eq_('%s' % Review.objects.get(id=218207).body, 'woo woo')

    def test_edit_not_owner(self):
        url = reverse('reviews.edit', args=['a1865', 218468])
        r = self.client.post(url, {'rating': 2, 'body': 'woo woo'},
                             X_REQUESTED_WITH='XMLHttpRequest')
        eq_(r.status_code, 403)

    def test_edit_reply(self):
        self.login_dev()
        url = reverse('reviews.edit', args=['a1865', 218468])
        r = self.client.post(url, {'title': 'fo', 'body': 'shizzle'},
                             X_REQUESTED_WITH='XMLHttpRequest')
        eq_(r.status_code, 200)
        review = Review.objects.get(id=218468)
        eq_('%s' % review.title, 'fo')
        eq_('%s' % review.body, 'shizzle')


class TestMobileReviews(TestMobile):
    fixtures = ['base/apps', 'reviews/dev-reply.json', 'base/admin',
                'base/users']

    def setUp(self):
        super(TestMobileReviews, self).setUp()
        self.addon = Addon.objects.get(id=1865)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.login_regular()
        self.add = reverse('reviews.add', args=['a1865'])
        self.list = reverse('reviews.list', args=['a1865'])

    def login_regular(self):
        self.client.login(username='regular@mozilla.com', password='password')

    def login_dev(self):
        self.client.login(username='trev@adblockplus.org', password='password')

    def test_mobile(self):
        self.client.logout()
        self.mobile_init()
        r = self.client.get(self.list)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'reviews/mobile/review_list.html')

    def test_add_visitor(self):
        self.client.logout()
        self.mobile_init()
        r = self.client.get(self.add)
        eq_(r.status_code, 302)

    def test_add_logged(self):
        r = self.client.get(self.add)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'reviews/mobile/add.html')

    def test_add_dev(self):
        self.login_dev()
        r = self.client.get(self.add)
        eq_(r.status_code, 403)

    def test_add_nonpurchased_premium(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        data = {'body': 'x', 'rating': 1}
        eq_(self.client.get(self.add).status_code, 403)
        eq_(self.client.post(self.add, data).status_code, 403)

    def test_add_purchased_premium(self):
        self.addon.addonpurchase_set.create(user=self.user)
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        data = {'body': 'x', 'rating': 1}
        eq_(self.client.get(self.add).status_code, 200)
        eq_(self.client.post(self.add, data).status_code, 302)

    def test_add_link_visitor(self):
        self.client.logout()
        self.mobile_init()
        r = self.client.get(self.list)
        doc = pq(r.content)
        eq_(doc('#add-review').length, 1)
        eq_(doc('.copy .login-button').length, 1)
        eq_(doc('#review-form').length, 0)

    def test_add_link_logged(self):
        r = self.client.get(self.list)
        doc = pq(r.content)
        eq_(doc('#add-review').length, 1)
        eq_(doc('#review-form').length, 1)

    def test_add_link_dev(self):
        self.login_dev()
        r = self.client.get(self.list)
        doc = pq(r.content)
        eq_(doc('#add-review').length, 0)
        eq_(doc('#review-form').length, 0)

    def test_add_submit(self):
        r = self.client.post(self.add, {'body': 'hi', 'rating': 3})
        eq_(r.status_code, 302)

        r = self.client.get(self.list)
        doc = pq(r.content)
        text = doc('.review').eq(0).text()
        assert "hi" in text
        assert "Rated 3 out of 5" in text

    def test_add_logged_out(self):
        self.client.logout()
        self.mobile_init()
        r = self.client.get(reverse('reviews.add', args=['a1865']))
        eq_(r.status_code, 302)
