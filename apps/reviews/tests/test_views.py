# -*- coding: utf-8 -*-
import json
from nose.tools import eq_
from pyquery import PyQuery as pq

import mock

import amo.tests
from amo import helpers
from access.models import Group, GroupUser
from addons.models import Addon, AddonUser
from devhub.models import ActivityLog
from reviews.models import Review, ReviewFlag
from users.models import UserProfile


class ReviewTest(amo.tests.TestCase):
    fixtures = ['reviews/dev-reply.json', 'base/admin']

    def setUp(self):
        super(ReviewTest, self).setUp()
        self.addon = Addon.objects.get(id=1865)

    def login_dev(self):
        self.client.login(username='trev@adblockplus.org', password='password')

    def login_admin(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')

    def make_it_my_review(self, review_id=218468):
        r = Review.objects.get(id=review_id)
        r.user = UserProfile.objects.get(username='jbalogh')
        r.save()


class TestViews(ReviewTest):

    def test_dev_reply(self):
        url = helpers.url('addons.reviews.detail', self.addon.slug, 218468)
        r = self.client.get(url)
        eq_(r.status_code, 200)

    def test_dev_no_rss(self):
        url = helpers.url('addons.reviews.detail', self.addon.slug, 218468)
        r = self.client.get(url)
        doc = pq(r.content)
        eq_(doc('link[title=RSS]').length, 0)

    def test_404_user_page(self):
        url = helpers.url('addons.reviews.user', self.addon.slug, 233452342)
        r = self.client.get(url)
        eq_(r.status_code, 404)

    def test_feed(self):
        url = helpers.url('addons.reviews.list.rss', self.addon.slug)
        r = self.client.get(url)
        eq_(r.status_code, 200)

    def test_abuse_form(self):
        r = self.client.get(helpers.url('addons.reviews.list',
                                        self.addon.slug))
        self.assertTemplateUsed(r, 'reviews/report_review.html')
        r = self.client.get(helpers.url('addons.reviews.detail',
                                        self.addon.slug, 218468))
        self.assertTemplateUsed(r, 'reviews/report_review.html')

    def test_edit_review_form(self):
        r = self.client.get(helpers.url('addons.reviews.list',
                                        self.addon.slug))
        self.assertTemplateUsed(r, 'reviews/edit_review.html')
        r = self.client.get(helpers.url('addons.reviews.detail',
                                        self.addon.slug, 218468))
        self.assertTemplateUsed(r, 'reviews/edit_review.html')

    def test_list(self):
        r = self.client.get(helpers.url('addons.reviews.list',
                                        self.addon.slug))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        reviews = doc('#reviews .item')
        eq_(reviews.length, Review.objects.count())
        eq_(Review.objects.count(), 2)
        eq_(doc('.secondary .average-rating').length, 1)
        eq_(doc('.secondary .no-rating').length, 0)

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

    def test_list_rss(self):
        r = self.client.get(helpers.url('addons.reviews.list',
                                        self.addon.slug))
        doc = pq(r.content)
        eq_(doc('link[title=RSS]').length, 1)

    def test_empty_list(self):
        Review.objects.all().delete()
        eq_(Review.objects.count(), 0)
        r = self.client.get(helpers.url('addons.reviews.list',
                                        self.addon.slug))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#reviews .item').length, 0)
        eq_(doc('#add-first-review').length, 1)
        eq_(doc('.secondary .average-rating').length, 0)
        eq_(doc('.secondary .no-rating').length, 1)

    def test_list_item_actions(self):
        self.login_admin()
        self.make_it_my_review()
        r = self.client.get(helpers.url('addons.reviews.list',
                                        self.addon.slug))
        reviews = pq(r.content)('#reviews .item')

        r = Review.objects.get(id=218207)
        item = reviews.filter('#review-218207')
        actions = item.find('.item-actions')
        eq_(actions.length, 1)
        classes = sorted(c.get('class') for c in actions.find('li a'))
        eq_(classes, ['delete-review', 'flag-review'])

        r = Review.objects.get(id=218468)
        item = reviews.filter('#review-218468')
        actions = item.find('.item-actions')
        eq_(actions.length, 1)
        classes = sorted(c.get('class') for c in actions.find('li a'))
        eq_(classes, ['delete-review', 'review-reply-edit'])

    def test_cant_view_unlisted_addon_reviews(self):
        """An unlisted addon doesn't have reviews."""
        self.addon.update(is_listed=False)
        assert self.client.get(helpers.url('addons.reviews.list',
                                           self.addon.slug)).status_code == 404


class TestFlag(ReviewTest):

    def setUp(self):
        super(TestFlag, self).setUp()
        self.url = helpers.url('addons.reviews.flag', self.addon.slug, 218468)
        self.login_admin()

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
        super(TestDelete, self).setUp()
        self.url = helpers.url('addons.reviews.delete',
                               self.addon.slug, 218207)
        self.login_admin()

    def test_no_login(self):
        self.client.logout()
        response = self.client.post(self.url)
        eq_(response.status_code, 401)

    def test_no_perms(self):
        GroupUser.objects.all().delete()
        response = self.client.post(self.url)
        eq_(response.status_code, 403)

    def test_404(self):
        url = helpers.url('addons.reviews.delete', self.addon.slug, 0)
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

    def test_delete_own_review(self):
        self.client.logout()
        self.login_dev()
        url = helpers.url('addons.reviews.delete', self.addon.slug, 218468)
        cnt = Review.objects.count()
        response = self.client.post(url)
        eq_(response.status_code, 200)
        eq_(Review.objects.count(), cnt - 1)
        eq_(Review.objects.filter(pk=218468).exists(), False)

    def test_reviewer_can_delete(self):
        # Test an editor can delete a review if not listed as an author.
        user = UserProfile.objects.get(email='trev@adblockplus.org')
        # Remove user from authors.
        AddonUser.objects.filter(addon=self.addon).delete()
        # Make user an add-on reviewer.
        group = Group.objects.create(name='Reviewer', rules='Addons:Review')
        GroupUser.objects.create(group=group, user=user)

        self.client.logout()
        self.login_dev()

        cnt = Review.objects.count()
        response = self.client.post(self.url)
        eq_(response.status_code, 200)
        # Two are gone since we deleted a review with a reply.
        eq_(Review.objects.count(), cnt - 2)
        eq_(Review.objects.filter(pk=218207).exists(), False)

    def test_editor_own_addon_cannot_delete(self):
        # Test an editor cannot delete a review if listed as an author.
        user = UserProfile.objects.get(email='trev@adblockplus.org')
        # Make user an add-on reviewer.
        group = Group.objects.create(name='Reviewer', rules='Addons:Review')
        GroupUser.objects.create(group=group, user=user)

        self.client.logout()
        self.login_dev()

        cnt = Review.objects.count()
        response = self.client.post(self.url)
        eq_(response.status_code, 403)
        eq_(Review.objects.count(), cnt)
        eq_(Review.objects.filter(pk=218207).exists(), True)


class TestCreate(ReviewTest):

    def setUp(self):
        super(TestCreate, self).setUp()
        self.add = helpers.url('addons.reviews.add', self.addon.slug)
        self.client.login(username='root_x@ukr.net', password='password')
        self.user = UserProfile.objects.get(email='root_x@ukr.net')
        self.qs = Review.objects.filter(addon=1865)
        self.log_count = ActivityLog.objects.count
        self.more = self.addon.get_url_path(more=True)
        self.list = helpers.url('addons.reviews.list', self.addon.slug)

    def test_add_logged(self):
        r = self.client.get(self.add)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'reviews/add.html')

    def test_add_admin(self):
        self.login_admin()

    def test_add_link_visitor(self):
        """
        Ensure non-logged user can see Add Review links on details page
        but not on Reviews listing page.
        """
        self.client.logout()
        r = self.client.get_ajax(self.more)
        eq_(pq(r.content)('#add-review').length, 1)
        r = self.client.get(helpers.url('addons.reviews.list',
                                        self.addon.slug))
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
        r = self.client.get(helpers.url('addons.reviews.list',
                                        self.addon.slug))
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

    def test_body_has_url(self):
        """ test that both the create and revise reviews segments properly
            note reviews that contain URL like patterns for editorial review
        """
        for body in ['url http://example.com', 'address 127.0.0.1',
                     'url https://example.com/foo/bar', 'host example.org',
                     'quote example%2eorg', 'IDNA www.xn--ie7ccp.xxx']:
            self.client.post(self.add, {'body': body, 'rating': 2})
            ff = Review.objects.filter(addon=self.addon)
            rf = ReviewFlag.objects.filter(review=ff[0])
            eq_(ff[0].flag, True)
            eq_(ff[0].editorreview, True)
            eq_(rf[0].note, 'URLs')

    def test_cant_review_unlisted_addon(self):
        """Can't review an unlisted addon."""
        self.addon.update(is_listed=False)
        assert self.client.get(self.add).status_code == 404


class TestEdit(ReviewTest):

    def setUp(self):
        super(TestEdit, self).setUp()
        self.client.login(username='root_x@ukr.net', password='password')

    def test_edit(self):
        url = helpers.url('addons.reviews.edit', self.addon.slug, 218207)
        response = self.client.post(url, {'rating': 2, 'body': 'woo woo'},
                                    X_REQUESTED_WITH='XMLHttpRequest')
        assert response.status_code == 200
        assert response['Content-type'] == 'application/json'
        assert '%s' % Review.objects.get(id=218207).body == 'woo woo'

        response = self.client.get(helpers.url('addons.reviews.list',
                                   self.addon.slug))
        doc = pq(response.content)
        assert doc('#review-218207 .review-edit').text() == 'Edit review'

    def test_edit_not_owner(self):
        url = helpers.url('addons.reviews.edit', self.addon.slug, 218468)
        r = self.client.post(url, {'rating': 2, 'body': 'woo woo'},
                             X_REQUESTED_WITH='XMLHttpRequest')
        eq_(r.status_code, 403)

    def test_edit_reply(self):
        self.login_dev()
        url = helpers.url('addons.reviews.edit', self.addon.slug, 218468)
        response = self.client.post(url, {'title': 'fo', 'body': 'shizzle'},
                                    X_REQUESTED_WITH='XMLHttpRequest')
        assert response.status_code == 200
        reply = Review.objects.get(id=218468)
        assert '%s' % reply.title == 'fo'
        assert '%s' % reply.body == 'shizzle'

        response = self.client.get(helpers.url('addons.reviews.list',
                                   self.addon.slug))
        doc = pq(response.content)
        assert doc('#review-218468 .review-reply-edit').text() == 'Edit reply'


class TestTranslate(ReviewTest):

    def setUp(self):
        super(TestTranslate, self).setUp()
        self.create_switch('reviews-translate')
        self.user = UserProfile.objects.get(username='jbalogh')
        self.review = Review.objects.create(addon=self.addon, user=self.user,
                                            title='or', body='yes')

    def test_regular_call(self):
        review = self.review
        url = helpers.url('addons.reviews.translate', review.addon.slug,
                          review.id, 'fr')
        r = self.client.get(url)
        eq_(r.status_code, 302)
        eq_(r.get('Location'), 'https://translate.google.com/#auto/fr/yes')

    def test_unicode_call(self):
        review = Review.objects.create(addon=self.addon, user=self.user,
                                       title='or', body=u'héhé 3%')
        url = helpers.url('addons.reviews.translate',
                          review.addon.slug, review.id, 'fr')
        r = self.client.get(url)
        eq_(r.status_code, 302)
        eq_(r.get('Location'),
            'https://translate.google.com/#auto/fr/h%C3%A9h%C3%A9%203%25')

    @mock.patch('reviews.views.requests')
    def test_ajax_call(self, requests):
        # Mock requests.
        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {u'data': {u'translations': [{
            u'translatedText': u'oui',
            u'detectedSourceLanguage': u'en'
        }]}}
        requests.get.return_value = response

        # Call translation.
        review = self.review
        url = helpers.url('addons.reviews.translate', review.addon.slug,
                          review.id, 'fr')
        r = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(r.status_code, 200)
        eq_(json.loads(r.content), {"body": "oui", "title": "oui"})

    @mock.patch('waffle.switch_is_active', lambda x: True)
    @mock.patch('reviews.views.requests')
    def test_invalid_api_key(self, requests):
        # Mock requests.
        response = mock.Mock()
        response.status_code = 400
        response.json.return_value = {'error': {'code': 400, 'errors': [{
            'domain': 'usageLimits', 'message': 'Bad Request',
            'reason': 'keyInvalid'}], 'message': 'Bad Request'}}
        requests.get.return_value = response

        # Call translation.
        review = self.review
        url = helpers.url('addons.reviews.translate', review.addon.slug,
                          review.id, 'fr')
        r = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(r.status_code, 400)


class TestMobileReviews(amo.tests.MobileTest, amo.tests.TestCase):
    fixtures = ['reviews/dev-reply.json', 'base/admin', 'base/users']

    def setUp(self):
        super(TestMobileReviews, self).setUp()
        self.addon = Addon.objects.get(id=1865)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.login_regular()
        self.add = helpers.url('addons.reviews.add', self.addon.slug)
        self.list = helpers.url('addons.reviews.list', self.addon.slug)

    def login_regular(self):
        self.client.login(username='regular@mozilla.com', password='password')

    def login_dev(self):
        self.client.login(username='trev@adblockplus.org', password='password')

    def login_admin(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')

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

    def test_add_admin(self):
        self.login_admin()
        r = self.client.get(self.add)
        eq_(r.status_code, 200)

    def test_add_dev(self):
        self.login_dev()
        r = self.client.get(self.add)
        eq_(r.status_code, 403)

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
        r = self.client.get(helpers.url('addons.reviews.add', self.addon.slug))
        eq_(r.status_code, 302)
