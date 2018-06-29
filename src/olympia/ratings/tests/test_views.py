# -*- coding: utf-8 -*-
import json

from datetime import timedelta

from django.core import mail
from django.core.cache import cache
from django.urls import reverse

import mock

from freezegun import freeze_time
from pyquery import PyQuery as pq

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonUser
from olympia.addons.utils import generate_addon_guid
from olympia.amo.templatetags import jinja_helpers
from olympia.amo.tests import (
    APITestClient, TestCase, addon_factory, user_factory, version_factory)
from olympia.ratings.models import Rating, RatingFlag
from olympia.users.models import UserProfile


class ReviewTest(TestCase):
    fixtures = ['ratings/dev-reply.json', 'base/admin']

    def setUp(self):
        super(ReviewTest, self).setUp()
        self.addon = Addon.objects.get(id=1865)

    def login_dev(self):
        self.client.login(email='trev@adblockplus.org')

    def login_admin(self):
        self.client.login(email='jbalogh@mozilla.com')

    def make_it_my_review(self, review_id=218468):
        r = Rating.objects.get(id=review_id)
        r.user = UserProfile.objects.get(username='jbalogh')
        r.save()


class TestViews(ReviewTest):

    def test_dev_reply(self):
        url = jinja_helpers.url(
            'addons.ratings.detail', self.addon.slug, 218468)
        r = self.client.get(url)
        assert r.status_code == 200

    def test_dev_no_rss(self):
        url = jinja_helpers.url(
            'addons.ratings.detail', self.addon.slug, 218468)
        r = self.client.get(url)
        doc = pq(r.content)
        assert doc('link[title=RSS]').length == 0

    def test_404_user_page(self):
        url = jinja_helpers.url(
            'addons.ratings.user', self.addon.slug, 233452342)
        r = self.client.get(url)
        assert r.status_code == 404

    def test_feed(self):
        url = jinja_helpers.url('addons.ratings.list.rss', self.addon.slug)
        r = self.client.get(url)
        assert r.status_code == 200

    def test_abuse_form(self):
        r = self.client.get(jinja_helpers.url(
            'addons.ratings.list', self.addon.slug))
        self.assertTemplateUsed(r, 'ratings/report_review.html')
        r = self.client.get(jinja_helpers.url(
            'addons.ratings.detail', self.addon.slug, 218468))
        self.assertTemplateUsed(r, 'ratings/report_review.html')

    def test_edit_review_form(self):
        r = self.client.get(jinja_helpers.url(
            'addons.ratings.list', self.addon.slug))
        self.assertTemplateUsed(r, 'ratings/edit_review.html')
        r = self.client.get(jinja_helpers.url(
            'addons.ratings.detail', self.addon.slug, 218468))
        self.assertTemplateUsed(r, 'ratings/edit_review.html')

    def test_list(self):
        r = self.client.get(jinja_helpers.url(
            'addons.ratings.list', self.addon.slug))
        assert r.status_code == 200
        doc = pq(r.content)
        reviews = doc('#reviews .item')
        assert reviews.length == Rating.objects.count()
        assert Rating.objects.count() == 2
        assert doc('.secondary .average-rating').length == 1
        assert doc('.secondary .no-rating').length == 0

        r = Rating.objects.get(id=218207)
        item = reviews.filter('#review-218207')
        assert r.reply_to_id is None
        assert not item.hasClass('reply')
        assert item.length == 1
        assert item.attr('data-rating') == str(r.rating)

        r = Rating.objects.get(id=218468)
        item = reviews.filter('#review-218468')
        assert item.length == 1
        assert r.reply_to_id == 218207
        assert item.hasClass('reply')
        assert r.rating is None
        assert item.attr('data-rating') == ''

    def test_empty_reviews_in_list(self):
        def create_review(body='review text', user=None):
            return Rating.objects.create(
                addon=self.addon, user=user or user_factory(),
                rating=3, body=body)

        url = jinja_helpers.url('addons.ratings.list', self.addon.slug)

        create_review()
        create_review(body=None)
        create_review(
            body=None,
            user=UserProfile.objects.get(email='trev@adblockplus.org'))

        # Don't show the reviews with no body.
        assert len(self.client.get(url).context['reviews']) == 2

        self.login_dev()
        # Except if it's your review
        assert len(self.client.get(url).context['reviews']) == 3

        # Or you're an admin
        self.login_admin()
        assert len(self.client.get(url).context['reviews']) == 4

    def test_list_rss(self):
        r = self.client.get(jinja_helpers.url(
            'addons.ratings.list', self.addon.slug))
        doc = pq(r.content)
        assert doc('link[title=RSS]').length == 1

    def test_empty_list(self):
        Rating.objects.all().delete()
        assert Rating.objects.count() == 0
        r = self.client.get(jinja_helpers.url(
            'addons.ratings.list', self.addon.slug))
        assert r.status_code == 200
        doc = pq(r.content)
        assert doc('#reviews .item').length == 0
        assert doc('#add-first-review').length == 1
        assert doc('.secondary .average-rating').length == 0
        assert doc('.secondary .no-rating').length == 1

    def test_list_item_actions(self):
        self.login_admin()
        self.make_it_my_review()
        r = self.client.get(jinja_helpers.url(
            'addons.ratings.list', self.addon.slug))
        reviews = pq(r.content)('#reviews .item')

        r = Rating.objects.get(id=218207)
        item = reviews.filter('#review-218207')
        actions = item.find('.item-actions')
        assert actions.length == 1
        classes = sorted(c.get('class') for c in actions.find('li a'))
        assert classes == ['delete-review', 'flag-review']

        r = Rating.objects.get(id=218468)
        item = reviews.filter('#review-218468')
        actions = item.find('.item-actions')
        assert actions.length == 1
        classes = sorted(c.get('class') for c in actions.find('li a'))
        assert classes == ['delete-review', 'review-reply-edit']

    def test_list_item_actions_already_flagged(self):
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        self.client.login(email=user.email)
        rating = Rating.objects.get(id=218207)
        RatingFlag.objects.create(rating=rating, user=user)
        response = self.client.get(jinja_helpers.url(
            'addons.ratings.list', self.addon.slug))
        assert response.status_code == 200
        reviews = pq(response.content)('#reviews .item')
        item = reviews.filter('#review-218207')
        actions = item.find('.item-actions')
        assert actions.length == 1
        classes = sorted(c.get('class') for c in actions.find('li a'))
        # flag-review action is absent since the user already flagged it.
        assert classes == ['delete-review']

    def test_cant_view_unlisted_addon_reviews(self):
        """An unlisted addon doesn't have reviews."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(jinja_helpers.url(
            'addons.ratings.list', self.addon.slug)).status_code == 404


class TestFlag(ReviewTest):

    def setUp(self):
        super(TestFlag, self).setUp()
        self.url = jinja_helpers.url(
            'addons.ratings.flag', self.addon.slug, 218468)
        self.login_admin()

    def test_no_login(self):
        self.client.logout()
        response = self.client.post(self.url)
        assert response.status_code == 401

    def test_new_flag(self):
        response = self.client.post(self.url, {'flag': RatingFlag.SPAM})
        assert response.status_code == 200
        assert response.content == (
            '{"msg": "Thanks; this review has been '
            'flagged for reviewer approval."}')
        assert RatingFlag.objects.filter(flag=RatingFlag.SPAM).count() == 1
        assert Rating.objects.filter(editorreview=True).count() == 1

    def test_new_flag_mine(self):
        self.make_it_my_review()
        response = self.client.post(self.url, {'flag': RatingFlag.SPAM})
        assert response.status_code == 403

    def test_flag_review_deleted(self):
        Rating.objects.get(pk=218468).delete()
        response = self.client.post(self.url, {'flag': RatingFlag.SPAM})
        assert response.status_code == 404

    def test_update_flag(self):
        response = self.client.post(self.url, {'flag': RatingFlag.SPAM})
        assert response.status_code == 200
        assert RatingFlag.objects.filter(flag=RatingFlag.SPAM).count() == 1
        assert Rating.objects.filter(editorreview=True).count() == 1

        response = self.client.post(self.url, {'flag': RatingFlag.LANGUAGE})
        assert response.status_code == 200
        assert RatingFlag.objects.filter(flag=RatingFlag.LANGUAGE).count() == 1
        assert RatingFlag.objects.count() == 1
        assert Rating.objects.filter(editorreview=True).count() == 1

    def test_flag_with_note(self):
        response = self.client.post(self.url,
                                    {'flag': RatingFlag.OTHER, 'note': 'xxx'})
        assert response.status_code == 200
        assert RatingFlag.objects.filter(flag=RatingFlag.OTHER).count() == (
            1)
        assert RatingFlag.objects.count() == 1
        assert RatingFlag.objects.get(flag=RatingFlag.OTHER).note == 'xxx'
        assert Rating.objects.filter(editorreview=True).count() == 1

    def test_bad_flag(self):
        response = self.client.post(self.url, {'flag': 'xxx'})
        assert response.status_code == 400
        assert Rating.objects.filter(editorreview=True).count() == 0

    def test_dont_flag_empty_rating(self):
        user = user_factory()
        review = Rating.objects.create(
            user=user, addon=self.addon, rating=3)
        flag_url = jinja_helpers.url(
            'addons.ratings.flag', self.addon.slug, review.id)
        response = self.client.post(flag_url, {'flag': RatingFlag.SPAM})
        assert response.content == (
            '{"msg": "This rating can\'t be flagged because it has no review '
            'text."}')


class TestDelete(ReviewTest):

    def setUp(self):
        super(TestDelete, self).setUp()
        self.url = jinja_helpers.url(
            'addons.ratings.delete', self.addon.slug, 218207)
        self.login_admin()

    def test_no_login(self):
        self.client.logout()
        response = self.client.post(self.url)
        assert response.status_code == 401

    def test_no_perms(self):
        GroupUser.objects.all().delete()
        response = self.client.post(self.url)
        assert response.status_code == 403

    def test_404(self):
        url = jinja_helpers.url('addons.ratings.delete', self.addon.slug, 0)
        response = self.client.post(url)
        assert response.status_code == 404

    def test_delete_review_with_dev_reply(self):
        cnt = Rating.objects.count()
        response = self.client.post(self.url)
        assert response.status_code == 200
        # Two are gone since we deleted a review with a reply.
        assert Rating.objects.count() == cnt - 2

    def test_delete_success(self):
        Rating.objects.update(reply_to=None)
        cnt = Rating.objects.count()
        response = self.client.post(self.url)
        assert response.status_code == 200
        assert Rating.objects.count() == cnt - 1

    def test_delete_own_review(self):
        self.client.logout()
        self.login_dev()
        url = jinja_helpers.url(
            'addons.ratings.delete', self.addon.slug, 218468)
        cnt = Rating.objects.count()
        response = self.client.post(url)
        assert response.status_code == 200
        assert Rating.objects.count() == cnt - 1
        assert not Rating.objects.filter(pk=218468).exists()

    def test_moderator_can_delete_flagged_review(self):
        # Test a moderator can delete a review if not listed as an author.
        user = UserProfile.objects.get(email='trev@adblockplus.org')
        # Remove user from authors.
        AddonUser.objects.filter(addon=self.addon).delete()
        # Make user a moderator.
        group = Group.objects.create(
            name='Reviewers: Moderators', rules='Ratings:Moderate')
        GroupUser.objects.create(group=group, user=user)
        # Make review pending moderation
        Rating.objects.get(pk=218207).update(editorreview=True)

        self.client.logout()
        self.login_dev()

        cnt = Rating.objects.count()
        response = self.client.post(self.url)
        assert response.status_code == 200
        # Two are gone since we deleted a review with a reply.
        assert Rating.objects.count() == cnt - 2
        assert not Rating.objects.filter(pk=218207).exists()

    def test_moderator_cannot_delete_unflagged_review(self):
        # Test a moderator can not delete a review if it's not flagged.
        user = UserProfile.objects.get(email='trev@adblockplus.org')
        # Remove user from authors.
        AddonUser.objects.filter(addon=self.addon).delete()
        # Make user an moderator.
        group = Group.objects.create(
            name='Reviewers: Moderators', rules='Ratings:Moderate')
        GroupUser.objects.create(group=group, user=user)

        self.client.logout()
        self.login_dev()

        cnt = Rating.objects.count()
        response = self.client.post(self.url)
        assert response.status_code == 403
        assert Rating.objects.count() == cnt
        assert Rating.objects.filter(pk=218207).exists()

    def test_moderator_own_addon_cannot_delete_review(self):
        # Test a moderator cannot delete a review if listed as an author.
        user = UserProfile.objects.get(email='trev@adblockplus.org')
        # Make user an moderator.
        group = Group.objects.create(
            name='Reviewers: Moderators', rules='Ratings:Moderate')
        GroupUser.objects.create(group=group, user=user)

        self.client.logout()
        self.login_dev()

        cnt = Rating.objects.count()
        response = self.client.post(self.url)
        assert response.status_code == 403
        assert Rating.objects.count() == cnt
        assert Rating.objects.filter(pk=218207).exists()


class TestCreate(ReviewTest):

    def setUp(self):
        super(TestCreate, self).setUp()
        self.add_url = jinja_helpers.url('addons.ratings.add', self.addon.slug)
        self.client.login(email='root_x@ukr.net')
        self.addon = Addon.objects.get(pk=1865)
        self.user = UserProfile.objects.get(email='root_x@ukr.net')
        self.qs = Rating.objects.filter(addon=self.addon)
        self.more_url = self.addon.get_url_path(more=True)
        self.list_url = jinja_helpers.url(
            'addons.ratings.list', self.addon.slug)

    def test_add_logged(self):
        r = self.client.get(self.add_url)
        assert r.status_code == 200
        self.assertTemplateUsed(r, 'ratings/add.html')

    def test_no_body(self):
        response = self.client.post(self.add_url, {'body': ''})
        self.assertFormError(
            response, 'form', 'body', 'This field is required.')
        assert len(mail.outbox) == 0

        response = self.client.post(self.add_url, {'body': ' \t \n '})
        self.assertFormError(
            response, 'form', 'body', 'This field is required.')
        assert len(mail.outbox) == 0

    def test_no_rating(self):
        r = self.client.post(self.add_url, {'body': 'no rating'})
        self.assertFormError(r, 'form', 'rating', 'This field is required.')
        assert len(mail.outbox) == 0

    def test_review_success(self):
        activity_qs = ActivityLog.objects.filter(action=amo.LOG.ADD_RATING.id)
        old_cnt = self.qs.count()
        log_count = activity_qs.count()
        response = self.client.post(self.add_url, {'body': 'xx', 'rating': 3})
        self.assertRedirects(response, self.list_url, status_code=302)
        assert self.qs.count() == old_cnt + 1
        # We should have an ADD_RATING entry now.
        assert activity_qs.count() == log_count + 1

        assert len(mail.outbox) == 1

        assert '3 out of 5' in mail.outbox[0].body, "Rating not included"
        self.assertTemplateUsed(response, 'ratings/emails/new_rating.txt')

    def test_reply_not_author_or_admin(self):
        url = jinja_helpers.url(
            'addons.ratings.reply', self.addon.slug, 218207)
        response = self.client.get(url)
        assert response.status_code == 403

        response = self.client.post(url, {'body': 'unst unst'})
        assert response.status_code == 403

    def test_get_reply(self):
        self.login_dev()
        url = jinja_helpers.url(
            'addons.ratings.reply', self.addon.slug, 218207)
        response = self.client.get(url)
        assert response.status_code == 200
        # We should have a form with title and body in that order.
        assert response.context['form'].fields.keys() == ['title', 'body']

    def test_new_reply(self):
        self.login_dev()
        user = user_factory()
        # Use a new review as a base - since we soft-delete reviews, we can't
        # just delete the existing review and reply from the fixtures, that
        # would be considered like an edit and not send the email.
        review = Rating.objects.create(
            user=user, addon=self.addon, body='A review', rating=3)
        url = jinja_helpers.url(
            'addons.ratings.reply', self.addon.slug, review.pk)
        response = self.client.post(url, {'body': 'unst unst'})
        self.assertRedirects(
            response,
            jinja_helpers.url(
                'addons.ratings.detail', self.addon.slug, review.pk))
        assert self.qs.filter(reply_to=review.pk).count() == 1

        assert len(mail.outbox) == 1
        self.assertTemplateUsed(response, 'ratings/emails/reply_review.ltxt')

    def test_double_reply(self):
        self.login_dev()
        url = jinja_helpers.url(
            'addons.ratings.reply', self.addon.slug, 218207)
        response = self.client.post(url, {'body': 'unst unst'})
        self.assertRedirects(
            response,
            jinja_helpers.url(
                'addons.ratings.detail', self.addon.slug, 218207))
        assert self.qs.filter(reply_to=218207).count() == 1
        review = Rating.objects.get(id=218468)
        assert unicode(review.body) == u'unst unst'

        # Not a new reply, no mail is sent.
        assert len(mail.outbox) == 0

    def test_post_br_in_body_are_replaced_by_newlines(self):
        response = self.client.post(
            self.add_url, {'body': 'foo<br>bar', 'rating': 3})
        self.assertRedirects(response, self.list_url, status_code=302)
        review = Rating.objects.latest('pk')
        assert unicode(review.body) == "foo\nbar"

    def test_add_link_visitor(self):
        """
        Ensure non-logged user can see Add Review links on details page
        and Reviews listing page.
        """
        self.client.logout()
        r = self.client.get_ajax(self.more_url)
        assert pq(r.content)('#add-review').length == 1
        r = self.client.get(jinja_helpers.url(
            'addons.ratings.list', self.addon.slug))
        doc = pq(r.content)
        assert doc('#add-review').length == 1
        assert doc('#add-first-review').length == 0

    def test_add_link_logged(self):
        """Ensure logged user can see Add Review links."""
        r = self.client.get_ajax(self.more_url)
        assert pq(r.content)('#add-review').length == 1
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        assert doc('#add-review').length == 1
        assert doc('#add-first-review').length == 0

    def test_add_link_dev(self):
        """Ensure developer cannot see Add Review links."""
        self.login_dev()
        r = self.client.get_ajax(self.more_url)
        assert pq(r.content)('#add-review').length == 0
        r = self.client.get(jinja_helpers.url(
            'addons.ratings.list', self.addon.slug))
        doc = pq(r.content)
        assert doc('#add-review').length == 0
        assert doc('#add-first-review').length == 0

    def test_list_none_add_review_link_visitor(self):
        """If no reviews, ensure visitor user cannot see Add Review link."""
        Rating.objects.all().delete()
        self.client.logout()
        r = self.client.get(self.list_url)
        doc = pq(r.content)('#reviews')
        assert doc('#add-review').length == 0
        assert doc('#no-add-first-review').length == 0
        assert doc('#add-first-review').length == 1

    def test_list_none_add_review_link_logged(self):
        """If no reviews, ensure logged user can see Add Review link."""
        Rating.objects.all().delete()
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        assert doc('#add-review').length == 1
        assert doc('#no-add-first-review').length == 0
        assert doc('#add-first-review').length == 1

    def test_list_none_add_review_link_dev(self):
        """If no reviews, ensure developer can see Add Review link."""
        Rating.objects.all().delete()
        self.login_dev()
        r = self.client.get(self.list_url)
        doc = pq(r.content)('#reviews')
        assert doc('#add-review').length == 0
        assert doc('#no-add-first-review').length == 1
        assert doc('#add-first-review').length == 0

    def test_body_has_url(self):
        """ test that both the create and revise reviews segments properly
            note reviews that contain URL like patterns for review
        """
        for body in ['url http://example.com', 'address 127.0.0.1',
                     'url https://example.com/foo/bar', 'host example.org',
                     'quote example%2eorg', 'IDNA www.xn--ie7ccp.xxx']:
            self.client.post(self.add_url, {'body': body, 'rating': 2})
            ff = Rating.objects.filter(addon=self.addon)
            rf = RatingFlag.objects.filter(rating=ff[0])
            assert ff[0].flag
            assert ff[0].editorreview
            assert rf[0].note == 'URLs'

    def test_mail_and_new_activity_log_on_post(self):
        assert not ActivityLog.objects.exists()
        self.client.post(self.add_url, {'body': u'sômething', 'rating': 2})
        review = self.addon.ratings.latest('pk')
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == self.user
        assert activity_log.arguments == [self.addon, review]
        assert activity_log.action == amo.LOG.ADD_RATING.id

        assert len(mail.outbox) == 1

    def test_mail_but_no_activity_log_on_reply(self):
        # Hard delete existing reply first, because reply() does
        # a get_or_create(), which would make that reply an edit, and that's
        # covered by the other test below.
        Rating.objects.filter(id=218468).delete(hard_delete=True)
        review = self.addon.ratings.get()
        ActivityLog.objects.all().delete()
        reply_url = jinja_helpers.url(
            'addons.ratings.reply', self.addon.slug, review.pk)
        self.login_dev()
        self.client.post(reply_url, {'body': u'Reeeeeply! Rëëëplyyy'})
        assert ActivityLog.objects.count() == 0

        assert len(mail.outbox) == 1

    def test_new_activity_log_on_reply_but_no_mail_if_one_already_exists(self):
        review = self.addon.ratings.get()
        existing_reply = Rating.objects.get(id=218468)
        assert not ActivityLog.objects.exists()
        reply_url = jinja_helpers.url(
            'addons.ratings.reply', self.addon.slug, review.pk)
        self.login_dev()
        self.client.post(reply_url, {'body': u'Reeeeeply! Rëëëplyyy'})
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == existing_reply.user
        assert activity_log.arguments == [self.addon, existing_reply]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert len(mail.outbox) == 0

    def test_cant_review_unlisted_addon(self):
        """Can't review an unlisted addon."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.add_url).status_code == 404


class TestEdit(ReviewTest):

    def setUp(self):
        super(TestEdit, self).setUp()
        self.client.login(email='root_x@ukr.net')

    def test_edit(self):
        url = jinja_helpers.url('addons.ratings.edit', self.addon.slug, 218207)
        response = self.client.post(url, {'rating': 2, 'body': 'woo woo'},
                                    X_REQUESTED_WITH='XMLHttpRequest')
        assert response.status_code == 200
        assert response['Content-type'] == 'application/json'
        assert '%s' % Rating.objects.get(id=218207).body == 'woo woo'

        response = self.client.get(jinja_helpers.url('addons.ratings.list',
                                   self.addon.slug))
        doc = pq(response.content)
        assert doc('#review-218207 .review-edit').text() == 'Edit review'

    def test_edit_error(self):
        url = jinja_helpers.url('addons.ratings.edit', self.addon.slug, 218207)
        response = self.client.post(url, {'rating': 5},
                                    X_REQUESTED_WITH='XMLHttpRequest')
        assert response.status_code == 400
        assert response['Content-type'] == 'application/json'
        data = json.loads(response.content)
        assert data['body'] == ['This field is required.']

    def test_edit_not_owner(self):
        url = jinja_helpers.url('addons.ratings.edit', self.addon.slug, 218468)
        r = self.client.post(url, {'rating': 2, 'body': 'woo woo'},
                             X_REQUESTED_WITH='XMLHttpRequest')
        assert r.status_code == 403

    def test_edit_deleted(self):
        Rating.objects.get(pk=218207).delete()
        url = jinja_helpers.url('addons.ratings.edit', self.addon.slug, 218207)
        response = self.client.post(url, {'rating': 2, 'body': 'woo woo'},
                                    X_REQUESTED_WITH='XMLHttpRequest')
        assert response.status_code == 404

    def test_edit_reply(self):
        self.login_dev()
        url = jinja_helpers.url('addons.ratings.edit', self.addon.slug, 218468)
        response = self.client.post(url, {'title': 'fo', 'body': 'shizzle'},
                                    X_REQUESTED_WITH='XMLHttpRequest')
        assert response.status_code == 200
        reply = Rating.objects.get(id=218468)
        assert '%s' % reply.title == 'fo'
        assert '%s' % reply.body == 'shizzle'

        response = self.client.get(jinja_helpers.url('addons.ratings.list',
                                   self.addon.slug))
        doc = pq(response.content)
        assert doc('#review-218468 .review-reply-edit').text() == 'Edit reply'

    def test_new_activity_log_but_no_mail_on_edit(self):
        review = Rating.objects.get(pk=218207)
        assert not ActivityLog.objects.exists()
        user = review.user
        edit_url = jinja_helpers.url(
            'addons.ratings.edit', self.addon.slug, review.pk)
        self.client.post(edit_url, {'body': u'Edîted.', 'rating': 1})
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == user
        assert activity_log.arguments == [self.addon, review]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert len(mail.outbox) == 0

    def test_new_activity_log_but_no_mail_on_edit_by_admin(self):
        review = Rating.objects.get(pk=218207)
        assert not ActivityLog.objects.exists()
        original_user = review.user
        admin_user = UserProfile.objects.get(pk=4043307)
        self.login_admin()
        edit_url = jinja_helpers.url(
            'addons.ratings.edit', self.addon.slug, review.pk)
        self.client.post(edit_url, {'body': u'Edîted.', 'rating': 1})
        review.reload()
        assert review.user == original_user
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == admin_user
        assert activity_log.arguments == [self.addon, review]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert len(mail.outbox) == 0

    def test_new_activity_log_but_no_mail_on_reply_edit(self):
        review = Rating.objects.get(pk=218468)
        assert not ActivityLog.objects.exists()
        user = review.user
        edit_url = jinja_helpers.url(
            'addons.ratings.edit', self.addon.slug, review.pk)
        self.login_dev()
        self.client.post(edit_url, {'body': u'Reeeeeply! Rëëëplyyy'})
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == user
        assert activity_log.arguments == [self.addon, review]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert len(mail.outbox) == 0


class TestRatingViewSetGet(TestCase):
    client_class = APITestClient
    list_url_name = 'v4:rating-list'
    detail_url_name = 'v4:rating-detail'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.url = reverse(self.list_url_name)

    def test_url_v3(self):
        assert reverse('v3:rating-list').endswith('/v3/reviews/review/')
        rating = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory())
        detail_url = reverse('v3:rating-detail', kwargs={'pk': rating.pk})
        assert detail_url.endswith('/v3/reviews/review/%d/' % rating.pk)

    def test_url_default(self):
        assert self.url.endswith('/v4/ratings/rating/')
        rating = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory())
        detail_url = reverse(self.detail_url_name, kwargs={'pk': rating.pk})
        assert detail_url.endswith('/v4/ratings/rating/%d/' % rating.pk)

    def test_list_addon(self, **kwargs):
        review1 = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory(),
            rating=1)
        review2 = Rating.objects.create(
            addon=self.addon, body='review 2', user=user_factory(),
            rating=2)
        review1.update(created=self.days_ago(1))
        # Add a review belonging to a different add-on, a reply, a deleted
        # review and another older review by the same user as the first review.
        # They should not be present in the list.
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=review1.user,
            rating=3)
        review_deleted.delete()
        Rating.objects.create(
            addon=self.addon, body='reply to review 1', reply_to=review1,
            user=user_factory())
        Rating.objects.create(
            addon=addon_factory(), body='review other addon',
            user=user_factory(), rating=4)
        older_review = Rating.objects.create(
            addon=self.addon, body='review same user/addon older',
            user=review1.user, rating=5)
        # We change `created` manually after the actual creation, so we need to
        # force a full refresh of the denormalized fields, because this
        # normally only happens at creation time.
        older_review.update(created=self.days_ago(42))
        older_review.update_denormalized_fields()
        assert review1.reload().is_latest is True
        assert older_review.reload().is_latest is False

        assert Rating.unfiltered.count() == 6

        params = {'addon': self.addon.pk}
        params.update(kwargs)
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['count'] == 2
        assert data['results']
        assert len(data['results']) == 2
        assert data['results'][0]['id'] == review2.pk
        assert data['results'][1]['id'] == review1.pk

        if 'show_grouped_ratings' not in kwargs:
            assert 'grouped_ratings' not in data
        return data

    def test_list_addon_queries(self):
        version1 = self.addon.current_version
        version2 = version_factory(addon=self.addon)
        review1 = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory(),
            rating=1, version=version1)
        review2 = Rating.objects.create(
            addon=self.addon, body='review 2', user=user_factory(),
            rating=2, version=version2)
        review3 = Rating.objects.create(
            addon=self.addon, body='review 3', user=user_factory(),
            rating=2, version=version1)
        review2.update(created=self.days_ago(1))
        review1.update(created=self.days_ago(2))

        assert Rating.unfiltered.count() == 3

        cache.clear()
        with self.assertNumQueries(6):
            # 6 queries:
            # - One for the ratings count (pagination)
            # - One for the ratings themselves
            # - One for the ratings translations
            # - One for the replies (there aren't any, but we don't know
            #   that without making a query)
            # - Two for opening and closing a transaction/savepoint
            #   (https://github.com/mozilla/addons-server/issues/3610)
            #
            # We patch get_addon_object() to avoid the add-on related queries,
            # which would pollute the result.
            with mock.patch('olympia.ratings.views.RatingViewSet'
                            '.get_addon_object') as get_addon_object:
                get_addon_object.return_value = self.addon
                response = self.client.get(self.url, {'addon': self.addon.pk})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['count'] == 3
        assert data['results']
        assert len(data['results']) == 3
        assert data['results'][0]['body'] == review3.body
        assert data['results'][1]['body'] == review2.body
        assert data['results'][2]['body'] == review1.body

    def test_list_addon_queries_with_replies(self):
        version1 = self.addon.current_version
        version2 = version_factory(addon=self.addon)
        review1 = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory(),
            rating=1, version=version1)
        review2 = Rating.objects.create(
            addon=self.addon, body='review 2', user=user_factory(),
            rating=2, version=version2)
        review3 = Rating.objects.create(
            addon=self.addon, body='review 3', user=user_factory(),
            rating=2, version=version1)
        review2.update(created=self.days_ago(1))
        review1.update(created=self.days_ago(2))
        reply1 = Rating.objects.create(
            addon=self.addon, body='reply to review 1', reply_to=review1,
            user=user_factory())
        reply2 = Rating.objects.create(
            addon=self.addon, body='reply to review 2', reply_to=review2,
            user=reply1.user)

        assert Rating.unfiltered.count() == 5

        cache.clear()
        with self.assertNumQueries(7):
            # 9 queries:
            # - One for the ratings count
            # - One for the ratings
            # - One for the ratings translations
            # - One for the ratings fields
            # - One for the ratings translations
            # - Two for opening and closing a transaction/savepoint
            #   (https://github.com/mozilla/addons-server/issues/3610)
            #
            # We patch get_addon_object() to avoid the add-on related queries,
            # which would pollute the result. In the real world those queries
            # would often be in the cache.
            with mock.patch('olympia.ratings.views.RatingViewSet'
                            '.get_addon_object') as get_addon_object:
                get_addon_object.return_value = self.addon
                response = self.client.get(self.url, {'addon': self.addon.pk})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['count'] == 3
        assert data['results']
        assert len(data['results']) == 3
        assert data['results'][0]['body'] == review3.body
        assert data['results'][0]['reply'] is None
        assert data['results'][1]['body'] == review2.body
        assert data['results'][1]['reply']['body'] == reply2.body
        assert data['results'][2]['body'] == review1.body
        assert data['results'][2]['reply']['body'] == reply1.body

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
        response = self.client.get(self.url, {
            'addon': self.addon.pk, 'show_grouped_ratings': 'blah'})
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data['detail'] == (
            'show_grouped_ratings parameter should be a boolean')

    def test_list_addon_unknown(self, **kwargs):
        params = {'addon': self.addon.pk + 42}
        params.update(kwargs)
        response = self.client.get(self.url, params)
        assert response.status_code == 404
        data = json.loads(response.content)
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
                addon=self.addon, user=user or user_factory(),
                rating=3, body=body)

        self.user = user_factory()

        create_review()
        create_review()
        create_review(body=None)
        create_review(body=None)
        create_review(body=None, user=self.user)

        # Do show the reviews with no body by default
        response = self.client.get(self.url, {'addon': self.addon.pk})
        data = json.loads(response.content)
        assert data['count'] == 5 == len(data['results'])

        self.client.login_api(self.user)
        # Unless you filter them out
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'filter': 'without_empty_body'})
        data = json.loads(response.content)
        assert data['count'] == 2 == len(data['results'])

        # And maybe you only want your own empty reviews
        response = self.client.get(
            self.url, {'addon': self.addon.pk,
                       'filter': 'without_empty_body,with_yours'})
        data = json.loads(response.content)
        assert data['count'] == 3 == len(data['results'])

    def test_list_user(self, **kwargs):
        self.user = user_factory()
        review1 = Rating.objects.create(
            addon=self.addon, body='review 1', user=self.user)
        review2 = Rating.objects.create(
            addon=self.addon, body='review 2', user=self.user)
        review1.update(created=self.days_ago(1))
        review2.update(created=self.days_ago(2))
        # Add a review belonging to a different user, a reply and a deleted
        # review. The reply should show up since it's made by the right user,
        # but the rest should be ignored.
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=self.user)
        review_deleted.delete()
        other_review = Rating.objects.create(
            addon=addon_factory(), body='review from other user',
            user=user_factory())
        reply = Rating.objects.create(
            addon=other_review.addon, body='reply to other user',
            reply_to=other_review, user=self.user)

        assert Rating.unfiltered.count() == 5

        params = {'user': self.user.pk}
        params.update(kwargs)
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['count'] == 3
        assert data['results']
        assert len(data['results']) == 3
        assert data['results'][0]['id'] == reply.pk
        assert data['results'][1]['id'] == review1.pk
        assert data['results'][2]['id'] == review2.pk
        return data

    def test_list_addon_and_user(self):
        self.user = user_factory()
        old_review = Rating.objects.create(
            addon=self.addon, body='old review', user=self.user)
        old_review.update(created=self.days_ago(42))
        recent_review = Rating.objects.create(
            addon=self.addon, body='recent review', user=self.user)
        # None of those extra reviews should show up.
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=self.user)
        review_deleted.delete()
        other_review = Rating.objects.create(
            addon=addon_factory(), body='review from other user',
            user=user_factory())
        Rating.objects.create(
            addon=other_review.addon, body='reply to other user',
            reply_to=other_review, user=self.user)  # right user, wrong addon.
        Rating.objects.create(
            addon=addon_factory(), body='review from other addon',
            user=self.user)

        assert Rating.unfiltered.count() == 6

        # Since we're filtering on both addon and user, only the most recent
        # review from self.user on self.addon should show up.
        params = {'addon': self.addon.pk, 'user': self.user.pk}
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['count'] == 1
        assert data['results']
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == recent_review.pk

    def test_list_addon_and_version(self):
        self.user = user_factory()
        old_version = self.addon.current_version
        other_version = version_factory(addon=self.addon)
        old_review = Rating.objects.create(
            addon=self.addon, body='old review', user=self.user,
            version=old_version)
        old_review.update(created=self.days_ago(42))
        other_review_same_addon = Rating.objects.create(
            addon=self.addon, body='review from other user',
            user=user_factory(), version=old_version)
        # None of those extra reviews should show up.
        recent_review = Rating.objects.create(
            addon=self.addon, body='recent review', user=self.user,
            version=other_version)
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=self.user)
        review_deleted.delete()
        Rating.objects.create(
            addon=other_review_same_addon.addon, body='reply to other user',
            reply_to=other_review_same_addon, user=self.user)
        Rating.objects.create(
            addon=addon_factory(), body='review from other addon',
            user=self.user)

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
        data = json.loads(response.content)
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
            addon=self.addon, body='old review', user=self.user,
            version=old_version)
        old_review.update(created=self.days_ago(42))
        # None of those extra reviews should show up.
        other_review_same_addon = Rating.objects.create(
            addon=self.addon, body='review from other user',
            user=user_factory(), version=old_version)
        recent_review = Rating.objects.create(
            addon=self.addon, body='recent review', user=self.user,
            version=other_version)
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=self.user)
        review_deleted.delete()
        Rating.objects.create(
            addon=other_review_same_addon.addon, body='reply to other user',
            reply_to=other_review_same_addon, user=self.user)
        Rating.objects.create(
            addon=addon_factory(), body='review from other addon',
            user=self.user)

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
        data = json.loads(response.content)
        assert data['count'] == 1
        assert data['results']
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == old_review.pk

    def test_list_user_and_addon_and_version(self):
        self.user = user_factory()
        old_version = self.addon.current_version
        other_version = version_factory(addon=self.addon)
        old_review = Rating.objects.create(
            addon=self.addon, body='old review', user=self.user,
            version=old_version)
        old_review.update(created=self.days_ago(42))
        # None of those extra reviews should show up.
        other_review_same_addon = Rating.objects.create(
            addon=self.addon, body='review from other user',
            user=user_factory(), version=old_version)
        recent_review = Rating.objects.create(
            addon=self.addon, body='recent review', user=self.user,
            version=other_version)
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=self.user)
        review_deleted.delete()
        Rating.objects.create(
            addon=other_review_same_addon.addon, body='reply to other user',
            reply_to=other_review_same_addon, user=self.user)
        Rating.objects.create(
            addon=addon_factory(), body='review from other addon',
            user=self.user)

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
            'version': old_version.pk
        }
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['count'] == 1
        assert data['results']
        assert len(data['results']) == 1
        assert data['results'][0]['id'] == old_review.pk

    def test_list_user_grouped_ratings_not_present(self):
        return
        data = self.test_list_user(show_grouped_ratings=1)
        assert 'grouped_ratings' not in data

    def test_list_no_addon_or_user_present(self):
        response = self.client.get(self.url)
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data['detail'] == 'Need an addon or user parameter'

    def test_detail(self):
        review = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory())
        self.url = reverse(self.detail_url_name, kwargs={'pk': review.pk})

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['id'] == review.pk

    def test_detail_reply(self):
        review = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory())
        reply = Rating.objects.create(
            addon=self.addon, body='reply to review', user=user_factory(),
            reply_to=review)
        self.url = reverse(self.detail_url_name, kwargs={'pk': reply.pk})

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['id'] == reply.pk

    def test_detail_deleted(self):
        review = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory())
        self.url = reverse(self.detail_url_name, kwargs={'pk': review.pk})
        review.delete()

        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_detail_deleted_reply(self):
        review = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory())
        reply = Rating.objects.create(
            addon=self.addon, body='reply to review', user=user_factory(),
            reply_to=review)
        reply.delete()
        self.url = reverse(self.detail_url_name, kwargs={'pk': review.pk})

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['id'] == review.pk
        assert data['reply'] is None

    def test_detail_show_deleted_admin(self):
        self.user = user_factory()
        self.grant_permission(self.user, 'Addons:Edit')
        self.client.login_api(self.user)
        review = Rating.objects.create(
            addon=self.addon, body='review', user=user_factory())
        reply = Rating.objects.create(
            addon=self.addon, body='reply to review', user=user_factory(),
            reply_to=review)
        reply.delete()
        review.delete()
        self.url = reverse(self.detail_url_name, kwargs={'pk': review.pk})

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['id'] == review.pk
        assert data['reply']
        assert data['reply']['id'] == reply.pk

    def test_list_by_admin_does_not_show_deleted_by_default(self):
        self.user = user_factory()
        self.grant_permission(self.user, 'Addons:Edit')
        self.client.login_api(self.user)
        review1 = Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory())
        review2 = Rating.objects.create(
            addon=self.addon, body='review 2', user=user_factory())
        review1.update(created=self.days_ago(1))
        # Add a review belonging to a different add-on, a reply and a deleted
        # review. They should not be present in the list.
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=review1.user)
        review_deleted.delete()
        Rating.objects.create(
            addon=self.addon, body='reply to review 2', reply_to=review2,
            user=user_factory())
        Rating.objects.create(
            addon=addon_factory(), body='review other addon',
            user=review1.user)
        # Also add a deleted reply to the first review, it should not be shown.
        deleted_reply = Rating.objects.create(
            addon=self.addon, body='reply to review 1', reply_to=review1,
            user=user_factory())
        deleted_reply.delete()

        assert Rating.unfiltered.count() == 6

        response = self.client.get(self.url, {'addon': self.addon.pk})
        assert response.status_code == 200
        data = json.loads(response.content)
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
            addon=self.addon, body='review 1', user=user_factory())
        review2 = Rating.objects.create(
            addon=self.addon, body='review 2', user=user_factory())
        review1.update(created=self.days_ago(1))
        # Add a review belonging to a different add-on, a reply and a deleted
        # review. The deleted review should be present, not the rest.
        review_deleted = Rating.objects.create(
            addon=self.addon, body='review deleted', user=review1.user)
        review_deleted.update(created=self.days_ago(2))
        review_deleted.delete()
        Rating.objects.create(
            addon=self.addon, body='reply to review 2', reply_to=review2,
            user=user_factory())
        Rating.objects.create(
            addon=addon_factory(), body='review other addon',
            user=review1.user)
        # Also add a deleted reply to the first review, it should be shown
        # as a child of that review.
        deleted_reply = Rating.objects.create(
            addon=self.addon, body='reply to review 1', reply_to=review1,
            user=user_factory())
        deleted_reply.delete()

        assert Rating.unfiltered.count() == 6

        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'filter': 'with_deleted'})
        assert response.status_code == 200
        data = json.loads(response.content)
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
        self.addon.update(slug=u'my-slûg')
        user = user_factory()
        Rating.objects.create(addon=self.addon, body='A review.', user=user)

        # No user, but addon is present.
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'user': u''})
        assert response.status_code == 200

        # No addon, but user is present.
        response = self.client.get(self.url, {'addon': u'', 'user': user.pk})
        assert response.status_code == 200

        # Addon parameter is utf-8.
        response = self.client.get(self.url, {'addon': u'my-slûg'})
        assert response.status_code == 200

        # User parameter is weird (it should be a pk, as string): 404.
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'user': u'çæ→'})
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data == {'detail': 'user parameter should be an integer.'}

        # Version parameter is weird (it should be a pk, as string): 404.
        response = self.client.get(
            self.url, {'addon': self.addon.pk, 'version': u'çæ→'})
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data == {'detail': 'version parameter should be an integer.'}

    # settings_test sets CACHE_COUNT_TIMEOUT to -1 and it's too late to
    # override it, so instead mock the TIMEOUT property in cache-machine.
    @mock.patch('caching.config.TIMEOUT', 300)
    def test_get_then_post_then_get_any_caching_is_cleared(self):
        """Make sure there is no overzealous caching going on when requesting
        the list of reviews for a given user+addon+version combination.
        Regression test for #5006."""
        self.user = user_factory()
        self.client.login_api(self.user)

        # Do a get filtering on both addon and user: it should not find
        # anything.
        response = self.client.get(self.url, {
            'addon': self.addon.pk,
            'version': self.addon.current_version.pk,
            'user': self.user.pk
        })
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data['results']) == 0
        assert data['count'] == 0

        # Do a post to add a review by this user.
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': u'blahé',
            'score': 5, 'version': self.addon.current_version.pk})
        assert response.status_code == 201

        # Re-do the same get as before, should now find something since the
        # view is avoiding count() caching in this case.
        response = self.client.get(self.url, {
            'addon': self.addon.pk,
            'version': self.addon.current_version.pk,
            'user': self.user.pk
        })
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data['results']) == 1
        assert data['count'] == 1

    def test_no_throttle(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        Rating.objects.create(
            addon=self.addon, body='review 1', user=user_factory(),
            rating=1)

        # We should be able to get as quick as we want.
        response = self.client.get(self.url, {'addon': self.addon.pk})
        assert response.status_code == 200
        response = self.client.get(self.url, {'addon': self.addon.pk})
        assert response.status_code == 200


class TestRatingViewSetDelete(TestCase):
    client_class = APITestClient
    detail_url_name = 'v4:rating-detail'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.user = user_factory()
        self.rating = Rating.objects.create(
            addon=self.addon, version=self.addon.current_version, rating=1,
            body='My review', user=self.user)
        self.url = reverse(self.detail_url_name, kwargs={'pk': self.rating.pk})

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
            addon=self.addon, reply_to=self.rating,
            body=u'Reply that will be delêted...', user=addon_author)
        self.url = reverse(self.detail_url_name, kwargs={'pk': reply.pk})

        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert Rating.objects.count() == 1
        assert Rating.unfiltered.count() == 2

    def test_delete_404(self):
        self.client.login_api(self.user)
        self.url = reverse(
            self.detail_url_name, kwargs={'pk': self.rating.pk + 42})
        response = self.client.delete(self.url)
        assert response.status_code == 404
        assert Rating.objects.count() == 1

    def test_no_throttle(self):
        # Add two reviews for different versions.
        rating_a = self.rating
        version_b = version_factory(addon=self.addon)
        rating_b = Rating.objects.create(
            addon=self.addon, version=version_b, rating=2,
            body='Second Review to delete', user=self.user)

        # And confirm we can rapidly delete them.
        self.client.login_api(self.user)
        response = self.client.delete(
            reverse(self.detail_url_name, kwargs={'pk': rating_a.pk}))
        assert response.status_code == 204
        response = self.client.delete(
            reverse(self.detail_url_name, kwargs={'pk': rating_b.pk}))
        assert response.status_code == 204
        assert Rating.objects.count() == 0


class TestRatingViewSetEdit(TestCase):
    client_class = APITestClient
    detail_url_name = 'v4:rating-detail'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.user = user_factory(username='areviewuser')
        self.rating = Rating.objects.create(
            addon=self.addon, version=self.addon.current_version, rating=1,
            body=u'My revïew', title=u'Titlé', user=self.user)
        self.url = reverse(self.detail_url_name, kwargs={'pk': self.rating.pk})

    def test_edit_anonymous(self):
        response = self.client.patch(self.url, {'body': u'løl!'})
        assert response.status_code == 401

        response = self.client.put(self.url, {'body': u'løl!'})
        assert response.status_code == 405

    def test_edit_no_rights(self):
        other_user = user_factory()
        self.client.login_api(other_user)
        response = self.client.patch(self.url, {'body': u'løl!'})
        assert response.status_code == 403

        response = self.client.put(self.url, {'body': u'løl!'})
        assert response.status_code == 405

    def test_edit_no_rights_even_reviewer(self):
        # Only admins can edit a review they didn't write themselves.
        reviewer_user = user_factory()
        self.grant_permission(reviewer_user, 'Addons:Review')
        self.client.login_api(reviewer_user)
        response = self.client.patch(self.url, {'body': u'løl!'})
        assert response.status_code == 403

        response = self.client.put(self.url, {'body': u'løl!'})
        assert response.status_code == 405

    def test_edit_owner_partial(self):
        original_created_date = self.days_ago(1)
        self.rating.update(created=original_created_date)
        self.client.login_api(self.user)
        response = self.client.patch(self.url, {'score': 2, 'body': u'løl!'})
        assert response.status_code == 200
        self.rating.reload()
        assert response.data['id'] == self.rating.pk
        assert response.data['body'] == unicode(self.rating.body) == u'løl!'
        assert response.data['title'] == unicode(self.rating.title) == u'Titlé'
        assert response.data['score'] == self.rating.rating == 2
        assert response.data['version'] == {
            'id': self.rating.version.id,
            'version': self.rating.version.version
        }
        assert self.rating.created == original_created_date

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == self.user
        assert activity_log.arguments == [self.addon, self.rating]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert len(mail.outbox) == 0

    def test_edit_owner_put_not_allowed(self):
        self.client.login_api(self.user)
        response = self.client.put(self.url, {'body': u'løl!'})
        assert response.status_code == 405

    def test_edit_dont_allow_version_to_be_edited(self):
        self.client.login_api(self.user)
        new_version = version_factory(addon=self.addon)
        response = self.client.patch(self.url, {'version': new_version.pk})
        assert response.status_code == 400
        assert response.data['version'] == [
            u"You can't change the version of the add-on reviewed once "
            u"the review has been created."]

    def test_edit_dont_allow_addon_to_be_edited(self):
        self.client.login_api(self.user)
        new_addon = addon_factory()
        response = self.client.patch(self.url, {'addon': new_addon.pk})
        assert response.status_code == 400
        assert response.data['addon'] == [
            u"You can't change the add-on of a review once it has been "
            u"created."]

    def test_edit_admin(self):
        original_review_user = self.rating.user
        admin_user = user_factory(username='mylittleadmin')
        self.grant_permission(admin_user, 'Addons:Edit')
        self.client.login_api(admin_user)
        response = self.client.patch(self.url, {'body': u'løl!'})
        assert response.status_code == 200
        self.rating.reload()
        assert response.data['id'] == self.rating.pk
        assert response.data['body'] == unicode(self.rating.body) == u'løl!'
        assert response.data['title'] == unicode(self.rating.title) == u'Titlé'
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
            reply_to=self.rating, body=u'This is â reply', user=addon_author,
            addon=self.addon)
        self.url = reverse(self.detail_url_name, kwargs={'pk': reply.pk})

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

    def test_no_throttle(self):
        self.client.login_api(self.user)
        response = self.client.patch(self.url, {'score': 2, 'body': u'nó!'})
        assert response.status_code == 200
        self.rating.reload()
        assert unicode(self.rating.body) == u'nó!'
        response = self.client.patch(self.url, {'score': 3, 'body': u'yés!'})
        assert response.status_code == 200
        self.rating.reload()
        assert unicode(self.rating.body) == u'yés!'


class TestRatingViewSetPost(TestCase):
    client_class = APITestClient
    list_url_name = 'v4:rating-list'
    abuse_report_url_name = 'v4:abusereportaddon-list'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.url = reverse(self.list_url_name)

    def test_post_anonymous(self):
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 5})
        assert response.status_code == 401

    def test_post_no_addon(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'body': u'test bodyé', 'title': None, 'score': 5,
            'version': self.addon.current_version.pk})
        assert response.status_code == 400
        assert response.data['addon'] == [u'This field is required.']

    def test_post_no_version(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 5})
        assert response.status_code == 400
        assert response.data['version'] == [u'This field is required.']

    def test_post_version_string(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 5, 'version': self.addon.current_version.version})
        assert response.status_code == 400
        assert response.data['version'] == [
            'Incorrect type. Expected pk value, received unicode.']

    def test_post_logged_in(self):
        addon_author = user_factory()
        self.addon.addonuser_set.create(user=addon_author)
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': u'blahé',
            'score': 5, 'version': self.addon.current_version.pk},
            REMOTE_ADDR='213.225.312.5')
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert unicode(review.body) == response.data['body'] == u'test bodyé'
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert unicode(review.title) == response.data['title'] == u'blahé'
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version
        }
        assert 'ip_address' not in response.data
        assert review.ip_address == '213.225.312.5'
        assert not review.flag
        assert not review.editorreview

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == self.user
        assert activity_log.arguments == [self.addon, review]
        assert activity_log.action == amo.LOG.ADD_RATING.id

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [addon_author.email]

    def test_post_auto_flagged_and_cleaned(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        body = u'Trying to spam <br> http://éxample.com'
        cleaned_body = u'Trying to spam \n http://éxample.com'
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': body, 'title': u'blahé',
            'score': 5, 'version': self.addon.current_version.pk})
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert unicode(review.body) == response.data['body'] == cleaned_body
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert unicode(review.title) == response.data['title'] == u'blahé'
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version
        }
        assert review.flag
        assert review.editorreview

    def test_post_rating_float(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 4.5, 'version': self.addon.current_version.pk})
        assert response.status_code == 400
        assert response.data['score'] == ['A valid integer is required.']

    def test_post_rating_too_big(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 6, 'version': self.addon.current_version.pk})
        assert response.status_code == 400
        assert response.data['score'] == [
            'Ensure this value is less than or equal to 5.']

    def test_post_rating_too_low(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 0, 'version': self.addon.current_version.pk})
        assert response.status_code == 400
        assert response.data['score'] == [
            'Ensure this value is greater than or equal to 1.']

    def test_post_rating_no_title(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 5, 'version': self.addon.current_version.pk})
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert unicode(review.body) == response.data['body'] == u'test bodyé'
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert review.title is None
        assert response.data['title'] is None
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version
        }

    def test_no_body_or_title_just_rating(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': None, 'title': None, 'score': 5,
            'version': self.addon.current_version.pk})
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert review.body is None
        assert response.data['body'] is None
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert review.title is None
        assert response.data['title'] is None
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version
        }

    def test_omit_body_and_title_completely_just_rating(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'score': 5,
            'version': self.addon.current_version.pk})
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert review.body is None
        assert response.data['body'] is None
        assert review.rating == response.data['score'] == 5
        assert review.user == self.user
        assert review.title is None
        assert response.data['title'] is None
        assert review.reply_to is None
        assert review.addon == self.addon
        assert review.version == self.addon.current_version
        assert response.data['version'] == {
            'id': review.version.id,
            'version': review.version.version
        }

    def test_post_rating_rating_required(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'version': self.addon.current_version.pk})
        assert response.status_code == 400
        assert response.data['score'] == ['This field is required.']

    def test_post_no_such_addon_id(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(self.url, {
            'addon': self.addon.pk + 42, 'body': 'test body', 'title': None,
            'score': 5, 'version': self.addon.current_version.pk})
        assert response.status_code == 404

    def test_post_version_not_linked_to_the_right_addon(self):
        addon2 = addon_factory()
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': 'test body', 'title': None,
            'score': 5, 'version': addon2.current_version.pk})
        assert response.status_code == 400
        assert response.data['version'] == [
            u"This version of the add-on doesn't exist or isn't public."]

    def test_post_deleted_addon(self):
        version_pk = self.addon.current_version.pk
        self.addon.delete()
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 5, 'version': version_pk})
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
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 5, 'version': old_version_pk})
        assert response.status_code == 400
        assert response.data['version'] == [
            u"This version of the add-on doesn't exist or isn't public."]

    def test_post_disabled_version(self):
        self.addon.current_version.update(created=self.days_ago(1))
        new_version = version_factory(addon=self.addon)
        old_version = self.addon.current_version
        old_version.files.update(status=amo.STATUS_DISABLED)
        assert self.addon.current_version == new_version
        assert self.addon.status == amo.STATUS_PUBLIC

        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 5, 'version': old_version.pk})
        assert response.status_code == 400
        assert response.data['version'] == [
            u"This version of the add-on doesn't exist or isn't public."]

    def test_post_not_public_addon(self):
        version_pk = self.addon.current_version.pk
        self.addon.update(status=amo.STATUS_NULL)
        self.user = user_factory()
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 5, 'version': version_pk})
        assert response.status_code == 403

    def test_post_logged_in_but_is_addon_author(self):
        self.user = user_factory()
        self.addon.addonuser_set.create(user=self.user)
        self.client.login_api(self.user)
        assert not Rating.objects.exists()
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'test bodyé', 'title': None,
            'score': 5, 'version': self.addon.current_version.pk})
        assert response.status_code == 400
        assert response.data['non_field_errors'] == [
            "You can't leave a review on your own add-on."]

    def test_post_twice_different_version(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        Rating.objects.create(
            addon=self.addon, version=self.addon.current_version, rating=1,
            body='My review', user=self.user)
        second_version = version_factory(addon=self.addon)
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'My ôther review', 'title': None,
            'score': 2, 'version': second_version.pk})
        assert response.status_code == 201
        assert Rating.objects.count() == 2

    def test_post_twice_same_version(self):
        # Posting a review more than once for the same version is not allowed.
        self.user = user_factory()
        self.client.login_api(self.user)
        Rating.objects.create(
            addon=self.addon, version=self.addon.current_version, rating=1,
            body='My review', user=self.user)
        response = self.client.post(self.url, {
            'addon': self.addon.pk, 'body': u'My ôther review', 'title': None,
            'score': 2, 'version': self.addon.current_version.pk})
        assert response.status_code == 400
        assert response.data['non_field_errors'] == [
            u"You can't leave more than one review for the same version of "
            u"an add-on."]

    def test_throttle(self):
        with freeze_time('2017-11-01') as frozen_time:
            self.user = user_factory()
            self.client.login_api(self.user)
            # First post, no problem.
            response = self.client.post(self.url, {
                'addon': self.addon.pk, 'body': u'My réview', 'title': None,
                'score': 2, 'version': self.addon.current_version.pk})
            assert response.status_code == 201

            # Add version so to avoid the one rating per version restriction.
            new_version = version_factory(addon=self.addon)
            # Second post, nope, have to wait a while.
            response = self.client.post(self.url, {
                'addon': self.addon.pk, 'body': u'My n3w réview',
                'title': None,
                'score': 2, 'version': new_version.pk})
            assert response.status_code == 429

            # Throttle is 1 minute so check we can go again
            frozen_time.tick(delta=timedelta(seconds=60))
            # And we're good.
            response = self.client.post(self.url, {
                'addon': self.addon.pk, 'body': u'My réview', 'title': None,
                'score': 2, 'version': new_version.pk})
            assert response.status_code == 201, response.content

    def test_rating_throttle_separated_from_abuse_throttle(self):
        with freeze_time('2017-11-01') as frozen_time:
            self.user = user_factory()
            self.client.login_api(self.user)

            # Submit an abuse report
            report_abuse_url = reverse(self.abuse_report_url_name)
            response = self.client.post(
                report_abuse_url,
                data={'addon': unicode(self.addon.pk), 'message': 'lol!'},
                REMOTE_ADDR='123.45.67.89')
            assert response.status_code == 201

            # Make sure you can still submit a rating after the abuse report.
            response = self.client.post(self.url, {
                'addon': self.addon.pk, 'body': u'My n3w réview',
                'title': None,
                'score': 2, 'version': self.addon.current_version.pk})
            assert response.status_code == 201

            # Add version so to avoid the one rating per version restriction.
            new_version = version_factory(addon=self.addon)
            # Second post, nope, have to wait a while.
            response = self.client.post(self.url, {
                'addon': self.addon.pk, 'body': u'My n3w réview',
                'title': None,
                'score': 2, 'version': new_version.pk})
            assert response.status_code == 429

            # We can still report abuse, it's a different throttle.
            response = self.client.post(
                report_abuse_url,
                data={'addon': unicode(self.addon.pk), 'message': 'again!'},
                REMOTE_ADDR='123.45.67.89')
            assert response.status_code == 201

            # Throttle is 1 minute so check we can go again
            frozen_time.tick(delta=timedelta(seconds=60))
            # And we're good.
            response = self.client.post(self.url, {
                'addon': self.addon.pk, 'body': u'My réview', 'title': None,
                'score': 2, 'version': new_version.pk})
            assert response.status_code == 201, response.content


class TestRatingViewSetFlag(TestCase):
    client_class = APITestClient
    flag_url_name = 'v4:rating-flag'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.rating_user = user_factory()
        self.rating = Rating.objects.create(
            addon=self.addon, version=self.addon.current_version, rating=1,
            body='My review', user=self.rating_user)
        self.url = reverse(self.flag_url_name, kwargs={'pk': self.rating.pk})

    def test_url_v3(self):
        expected_url = '/v3/reviews/review/%d/flag/' % self.rating.pk
        v3_url = reverse('v3:rating-flag', kwargs={'pk': self.rating.pk})
        assert v3_url.endswith(expected_url)

    def test_url_default(self):
        expected_url = '/v4/ratings/rating/%d/flag/' % self.rating.pk
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
        data = json.loads(response.content)
        assert data['flag'] == [u'This field is required.']
        assert self.rating.reload().editorreview is False

    def test_flag_logged_in(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(
            self.url, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 202
        data = json.loads(response.content)
        assert data == {
            'msg':
                'Thanks; this review has been flagged for reviewer approval.'
        }
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
            self.url, data={'flag': 'review_flag_reason_spam',
                            'note': u'This is my nøte.'})
        assert response.status_code == 202
        assert RatingFlag.objects.count() == 1
        flag = RatingFlag.objects.latest('pk')
        # Flag was changed automatically since a note is being posted.
        assert flag.flag == 'review_flag_reason_other'
        assert flag.user == self.user
        assert flag.rating == self.rating
        assert flag.note == u'This is my nøte.'
        assert self.rating.reload().editorreview is True

    def test_flag_reason_other_without_notes_is_forbidden(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(
            self.url, data={'flag': 'review_flag_reason_other'})
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data['note'] == [
            'A short explanation must be provided when selecting "Other" as a'
            ' flag reason.']

    def test_flag_logged_in_unknown_flag_type(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(
            self.url, data={'flag': 'lol'})
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data['flag'] == [
            'Select a valid choice. lol is not one of the available choices.']
        assert self.rating.reload().editorreview is False

    def test_flag_logged_in_flag_already_exists(self):
        other_user = user_factory()
        other_flag = RatingFlag.objects.create(
            user=other_user, rating=self.rating,
            flag='review_flag_reason_language')
        self.user = user_factory()
        flag = RatingFlag.objects.create(
            user=self.user, rating=self.rating,
            flag='review_flag_reason_other')
        self.client.login_api(self.user)
        response = self.client.post(
            self.url, data={'flag': 'review_flag_reason_spam'})
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
        response = self.client.post(
            self.url, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 403
        assert self.rating.reload().editorreview is False

    def test_flag_logged_in_no_such_review(self):
        self.rating.delete()
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self.client.post(
            self.url, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 404
        assert Rating.unfiltered.get(pk=self.rating.pk).editorreview is False

    def test_flag_logged_in_review_author(self):
        self.client.login_api(self.rating_user)
        response = self.client.post(
            self.url, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 403
        assert self.rating.reload().editorreview is False

    def test_no_throttle(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        # Create another addon for us to flag
        addon_b = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        rating_b = Rating.objects.create(
            addon=addon_b, version=addon_b.current_version, rating=2,
            body='My review', user=self.rating_user)
        url_b = reverse(self.flag_url_name, kwargs={'pk': rating_b.pk})

        response = self.client.post(
            self.url, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 202
        response = self.client.post(
            url_b, data={'flag': 'review_flag_reason_spam'})
        assert response.status_code == 202
        # Both should have been flagged.
        assert RatingFlag.objects.count() == 2


class TestRatingViewSetReply(TestCase):
    client_class = APITestClient
    reply_url_name = 'v4:rating-reply'

    def setUp(self):
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.rating_user = user_factory()
        self.rating = Rating.objects.create(
            addon=self.addon, version=self.addon.current_version, rating=1,
            body='My review', user=self.rating_user)
        self.url = reverse(self.reply_url_name, kwargs={'pk': self.rating.pk})

    def test_url_v3(self):
        v3_url = reverse('v3:rating-reply', kwargs={'pk': self.rating.pk})
        expected_url = '/api/v3/reviews/review/%d/reply/' % self.rating.pk
        assert v3_url.endswith(expected_url)

    def test_url_default(self):
        expected_url = '/api/v4/ratings/rating/%d/reply/' % self.rating.pk
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
        self.url = reverse(
            self.reply_url_name, kwargs={'pk': self.rating.pk + 42})
        response = self.client.post(self.url, data={})
        assert response.status_code == 404

    def test_reply_admin(self):
        self.admin_user = user_factory()
        self.grant_permission(self.admin_user, 'Addons:Edit')
        self.client.login_api(self.admin_user)
        response = self.client.post(self.url, data={
            'body': u'My âdmin réply...',
        })
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert review.body == response.data['body'] == u'My âdmin réply...'
        assert review.rating is None
        assert 'score' not in response.data
        assert review.user == self.admin_user
        assert review.title is None
        assert response.data['title'] is None
        assert review.reply_to == self.rating
        assert 'reply_to' not in response.data  # It's already in the URL...
        assert review.addon == self.addon
        assert review.version is None
        assert 'version' not in response.data

        assert not ActivityLog.objects.exists()

        assert len(mail.outbox) == 1

    def test_reply(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        self.client.login_api(self.addon_author)
        response = self.client.post(self.url, data={
            'body': u'My réply...',
        })
        assert response.status_code == 201
        review = Rating.objects.latest('pk')
        assert review.pk == response.data['id']
        assert review.body == response.data['body'] == u'My réply...'
        assert review.rating is None
        assert 'score' not in response.data
        assert review.user == self.addon_author
        assert review.title is None
        assert response.data['title'] is None
        assert review.reply_to == self.rating
        assert 'reply_to' not in response.data  # It's already in the URL...
        assert review.addon == self.addon
        assert review.version is None
        assert 'version' not in response.data

        assert not ActivityLog.objects.exists()

        assert len(mail.outbox) == 1

    def test_reply_if_a_reply_already_exists_updates_existing(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        existing_reply = Rating.objects.create(
            reply_to=self.rating, user=self.addon_author,
            addon=self.addon, body=u'My existing rêply')
        self.client.login_api(self.addon_author)
        response = self.client.post(self.url, data={
            'body': u'My réply...',
        })
        assert response.status_code == 200
        data = json.loads(response.content)
        assert Rating.objects.count() == 2
        existing_reply.reload()
        assert unicode(existing_reply.body) == data['body'] == u'My réply...'

    def test_reply_if_an_existing_reply_was_deleted_updates_existing(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        existing_reply = Rating.objects.create(
            reply_to=self.rating, user=self.addon_author,
            addon=self.addon, body=u'My existing rêply')
        existing_reply.delete()  # Soft delete the existing reply.
        assert Rating.objects.count() == 1
        assert Rating.unfiltered.count() == 2
        self.client.login_api(self.addon_author)
        response = self.client.post(self.url, data={
            'body': u'My réply...',
        })
        assert response.status_code == 200
        data = json.loads(response.content)
        assert Rating.objects.count() == 2  # No longer deleted.
        assert Rating.unfiltered.count() == 2
        existing_reply.reload()
        assert unicode(existing_reply.body) == data['body'] == u'My réply...'
        assert existing_reply.deleted is False

    def test_reply_disabled_addon(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        self.client.login_api(self.addon_author)
        self.addon.update(disabled_by_user=True)
        response = self.client.post(self.url, data={})
        assert response.status_code == 403

    def test_replying_to_a_reply_is_not_possible(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        self.client.login_api(self.addon_author)
        self.original_review = Rating.objects.create(
            addon=self.addon, version=self.addon.current_version, rating=1,
            body='My review', user=self.rating_user)
        self.rating.update(
            user=self.addon_author, rating=None, reply_to=self.original_review)
        response = self.client.post(self.url, data={
            'body': u'LOL øø!'
        })
        assert response.status_code == 400
        assert response.data['non_field_errors'] == [
            u"You can't reply to a review that is already a reply."]

    def test_throttle(self):
        self.addon_author = user_factory()
        self.addon.addonuser_set.create(user=self.addon_author)
        other_rating = Rating.objects.create(
            addon=self.addon, version=self.addon.current_version, rating=1,
            body='My review', user=user_factory())
        other_url = reverse(self.reply_url_name,
                            kwargs={'pk': other_rating.pk})

        with freeze_time('2017-11-01') as frozen_time:
            self.client.login_api(self.addon_author)
            # First post, no problem.
            response = self.client.post(self.url, data={
                'body': u'My réply...',
            })
            assert response.status_code == 201

            # Throttle is 1 per 5 seconds so after 4 seconds we have to wait
            frozen_time.tick(delta=timedelta(seconds=4))
            # Second post, nope, have to wait a while.
            response = self.client.post(other_url, data={
                'body': u'Another réply',
            })
            assert response.status_code == 429

            frozen_time.tick(delta=timedelta(seconds=5))
            # And we're good.
            response = self.client.post(other_url, data={
                'body': u'Really réply!',
            })
            assert response.status_code == 201
