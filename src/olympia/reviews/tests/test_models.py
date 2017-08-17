# -*- coding: utf-8 -*-
import mock

from django.core import mail
from django.utils import translation

from olympia import amo
from olympia.amo.templatetags import jinja_helpers
from olympia.activity.models import ActivityLog
from olympia.amo.tests import addon_factory, TestCase, ESTestCase, user_factory
from olympia.addons.models import Addon
from olympia.reviews import tasks
from olympia.reviews.models import GroupedRating, Review, ReviewFlag
from olympia.users.models import UserProfile


class TestReviewModel(TestCase):
    fixtures = ['reviews/test_models']

    def test_translations(self):
        translation.activate('en-US')

        # There's en-US and de translations.  We should get en-US.
        r1 = Review.objects.get(id=1)
        self.trans_eq(r1.title, 'r1 title en', 'en-US')

        # There's only a de translation, so we get that.
        r2 = Review.objects.get(id=2)
        self.trans_eq(r2.title, 'r2 title de', 'de')

        translation.activate('de')

        # en and de exist, we get de.
        r1 = Review.objects.get(id=1)
        self.trans_eq(r1.title, 'r1 title de', 'de')

        # There's only a de translation, so we get that.
        r2 = Review.objects.get(id=2)
        self.trans_eq(r2.title, 'r2 title de', 'de')

    def test_soft_delete(self):
        assert Review.objects.count() == 2
        assert Review.unfiltered.count() == 2

        Review.objects.get(id=1).delete()

        assert Review.objects.count() == 1
        assert Review.without_replies.count() == 1
        assert Review.unfiltered.count() == 2

        review = Review.objects.get(id=2)
        assert review.previous_count == 0
        assert review.is_latest is True

    @mock.patch('olympia.reviews.models.log')
    def test_soft_delete_user_responsible(self, log_mock):
        user_responsible = user_factory()
        review = Review.objects.get(id=1)
        review.delete(user_responsible=user_responsible)
        assert log_mock.info.call_count == 1
        assert (log_mock.info.call_args[0][0] ==
                'Review deleted: %s deleted id:%s by %s ("%s": "%s")')
        assert log_mock.info.call_args[0][1] == user_responsible.name
        assert log_mock.info.call_args[0][2] == review.pk
        assert log_mock.info.call_args[0][3] == review.user.name
        assert log_mock.info.call_args[0][4] == unicode(review.title)
        assert log_mock.info.call_args[0][5] == unicode(review.body)

    def test_hard_delete(self):
        # Hard deletion is only for tests, but it's still useful to make sure
        # it's working properly.
        assert Review.unfiltered.count() == 2
        Review.objects.filter(id=1).delete(hard_delete=True)
        assert Review.unfiltered.count() == 1
        assert Review.objects.filter(id=2).exists()

    def test_undelete(self):
        self.test_soft_delete()
        deleted_review = Review.unfiltered.get(id=1)
        assert deleted_review.deleted is True
        deleted_review.undelete()

        # The deleted_review was the oldest, so loading the other one we should
        # see an updated previous_count, and is_latest should still be True.
        review = Review.objects.get(id=2)
        assert review.previous_count == 1
        assert review.is_latest is True

    def test_soft_delete_replies_are_hidden(self):
        review = Review.objects.get(pk=1)
        Review.objects.create(
            addon=review.addon, reply_to=review,
            user=UserProfile.objects.all()[0])
        assert Review.objects.count() == 3
        assert Review.unfiltered.count() == 3
        assert Review.without_replies.count() == 2

        Review.objects.get(id=1).delete()

        # objects should only have 1 object, because we deleted the parent
        # review of the one we just created, so it should not be returned.
        assert Review.objects.count() == 1

        # without_replies should also only have 1 object, because, because it
        # does not include replies anyway.
        assert Review.without_replies.count() == 1

        # Unfiltered should have them all still.
        assert Review.unfiltered.count() == 3

    @mock.patch('olympia.reviews.models.log')
    def test_author_delete(self, log_mock):
        review = Review.objects.get(pk=1)
        review.delete(user_responsible=review.user)

        review.reload()
        assert ActivityLog.objects.count() == 0

    @mock.patch('olympia.reviews.models.log')
    def test_moderator_delete(self, log_mock):
        moderator = user_factory()
        review = Review.objects.get(pk=1)
        review.update(editorreview=True)
        review.reviewflag_set.create()
        review.delete(user_responsible=moderator)

        review.reload()
        assert ActivityLog.objects.count() == 1
        assert not review.reviewflag_set.exists()

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.details == {
            'body': 'None',
            'is_flagged': True,
            'addon_title': 'my addon name',
            'addon_id': 4,
            'title': 'r1 title en'
        }
        assert activity_log.user == moderator
        assert activity_log.action == amo.LOG.DELETE_REVIEW.id
        assert activity_log.arguments == [review.addon, review]

        assert log_mock.info.call_count == 1
        assert (log_mock.info.call_args[0][0] ==
                'Review deleted: %s deleted id:%s by %s ("%s": "%s")')
        assert log_mock.info.call_args[0][1] == moderator.name
        assert log_mock.info.call_args[0][2] == review.pk
        assert log_mock.info.call_args[0][3] == review.user.name
        assert log_mock.info.call_args[0][4] == unicode(review.title)
        assert log_mock.info.call_args[0][5] == unicode(review.body)

    def test_moderator_approve(self):
        moderator = user_factory()
        review = Review.objects.get(pk=1)
        review.update(editorreview=True)
        review.reviewflag_set.create()
        review.approve(user=moderator)

        review.reload()
        assert ActivityLog.objects.count() == 1
        assert not review.reviewflag_set.exists()
        assert review.editorreview is False

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.details == {
            'body': 'None',
            'is_flagged': True,
            'addon_title': 'my addon name',
            'addon_id': 4,
            'title': 'r1 title en'
        }
        assert activity_log.user == moderator
        assert activity_log.action == amo.LOG.APPROVE_REVIEW.id
        assert activity_log.arguments == [review.addon, review]

    def test_filter_for_many_to_many(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        review = Review.objects.get(id=1)
        addon = review.addon
        assert review in addon._reviews.all()

        # Delete the review: it shouldn't be listed anymore.
        review.delete()
        addon = Addon.objects.get(pk=addon.pk)
        assert review not in addon._reviews.all()

    def test_no_filter_for_relations(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        review = Review.objects.get(id=1)
        flag = ReviewFlag.objects.create(review=review,
                                         flag='review_flag_reason_spam')
        assert flag.review == review

        # Delete the review: reviewflag.review should still work.
        review.delete(user_responsible=review.user)
        flag = ReviewFlag.objects.get(pk=flag.pk)
        assert flag.review == review

    def test_creation_triggers_email_and_logging(self):
        addon = Addon.objects.get(pk=4)
        addon_author = addon.authors.first()
        review_user = user_factory()
        review = Review.objects.create(
            user=review_user, addon=addon,
            body=u'Rêviiiiiiew', user_responsible=review_user)

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == review_user
        assert activity_log.arguments == [addon, review]
        assert activity_log.action == amo.LOG.ADD_REVIEW.id

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        reply_url = jinja_helpers.absolutify(
            jinja_helpers.url(
                'addons.reviews.reply', addon.slug, review.pk,
                add_prefix=False))
        assert email.subject == 'Mozilla Add-on User Review: my addon name'
        assert 'A user has left a review for your add-on,' in email.body
        assert 'my addon name' in email.body
        assert reply_url in email.body
        assert email.to == [addon_author.email]
        assert email.from_email == 'Mozilla Add-ons <nobody@mozilla.org>'

    def test_reply_triggers_email_but_no_logging(self):
        review = Review.objects.get(id=1)
        user = user_factory()
        Review.objects.create(
            reply_to=review, user=user, addon=review.addon,
            body=u'Rêply', user_responsible=user)

        assert not ActivityLog.objects.exists()
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        reply_url = jinja_helpers.absolutify(
            jinja_helpers.url(
                'addons.reviews.detail', review.addon.slug, review.pk,
                add_prefix=False))
        assert email.subject == 'Mozilla Add-on Developer Reply: my addon name'
        assert 'A developer has replied to your review' in email.body
        assert 'add-on my addon name' in email.body
        assert reply_url in email.body
        assert email.to == ['arya@example.com']
        assert email.from_email == 'Mozilla Add-ons <nobody@mozilla.org>'

    def test_edit_triggers_logging_but_no_email(self):
        review = Review.objects.get(id=1)
        assert not ActivityLog.objects.exists()
        assert mail.outbox == []

        review.user_responsible = review.user
        review.body = u'Editëd...'
        review.save()

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == review.user
        assert activity_log.arguments == [review.addon, review]
        assert activity_log.action == amo.LOG.EDIT_REVIEW.id

        assert mail.outbox == []

    def test_edit_reply_triggers_logging_but_no_email(self):
        review = Review.objects.get(id=1)
        reply = Review.objects.create(
            reply_to=review, user=user_factory(), addon=review.addon)
        assert not ActivityLog.objects.exists()
        assert mail.outbox == []

        reply.user_responsible = reply.user
        reply.body = u'Actuälly...'
        reply.save()

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == reply.user
        assert activity_log.arguments == [reply.addon, reply]
        assert activity_log.action == amo.LOG.EDIT_REVIEW.id

        assert mail.outbox == []

    def test_non_user_edit_triggers_nothing(self):
        review = Review.objects.get(pk=1)
        review.previous_count = 42
        review.save()
        assert not ActivityLog.objects.exists()
        assert mail.outbox == []


class TestGroupedRating(TestCase):
    @classmethod
    # Prevent <Review>.refresh() from being fired when setting up test data,
    # since it'd affect the results of our tests by calculating GroupedRating
    # results early (and storing result in cache) or changing is_latest boolean
    # on reviews.
    @mock.patch.object(Review, 'refresh', lambda x, update_denorm=False: None)
    def setUpTestData(cls):
        cls.addon = addon_factory()
        user = user_factory()

        # Create a few reviews with various ratings.
        review = Review.objects.create(addon=cls.addon, rating=3, user=user)
        Review.objects.create(addon=cls.addon, rating=3, user=user_factory())
        Review.objects.create(addon=cls.addon, rating=2, user=user_factory())
        Review.objects.create(addon=cls.addon, rating=1, user=user_factory())
        Review.objects.create(addon=cls.addon, rating=1, user=user_factory())
        Review.objects.create(addon=cls.addon, rating=1, user=user_factory())

        # GroupedRating should ignore replies, so let's add one.
        Review.objects.create(
            addon=cls.addon, rating=5, user=user_factory(), reply_to=review)

        # GroupedRating should also ignore reviews that aren't the latest for
        # this user and addon, so let's add another one from the same user.
        Review.objects.create(
            addon=cls.addon, rating=4, user=user, is_latest=False)

        # There are three '1' ratings, one '2' rating, 2 'three' ratings,
        # and zero for '4' and '5' since replies and non-latest reviews do not
        # count.
        cls.expected_grouped_rating = [(1, 3), (2, 1), (3, 2), (4, 0), (5, 0)]

    def test_get_unknown_addon_id(self):
        assert GroupedRating.get(3, update_none=False) is None
        assert GroupedRating.get(3) == [(1, 0), (2, 0), (3, 0), (4, 0), (5, 0)]

    def test_set(self):
        assert GroupedRating.get(self.addon.pk, update_none=False) is None
        GroupedRating.set(self.addon.pk)
        assert GroupedRating.get(self.addon.pk, update_none=False) == (
            self.expected_grouped_rating)

    def test_cron(self):
        assert GroupedRating.get(self.addon.pk, update_none=False) is None
        tasks.addon_grouped_rating(self.addon.pk)
        assert GroupedRating.get(self.addon.pk, update_none=False) == (
            self.expected_grouped_rating)

    def test_update_none(self):
        assert GroupedRating.get(self.addon.pk, update_none=False) is None
        assert GroupedRating.get(self.addon.pk, update_none=True) == (
            self.expected_grouped_rating)


class TestRefreshTest(ESTestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestRefreshTest, self).setUp()
        self.addon = addon_factory()
        self.user = UserProfile.objects.all()[0]
        self.refresh()

        assert self.get_bayesian_rating() == 0.0

    def get_bayesian_rating(self):
        q = Addon.search().filter(id=self.addon.id)
        return q.values_dict('bayesian_rating')[0]['bayesian_rating']

    def test_created(self):
        assert self.get_bayesian_rating() == 0.0
        Review.objects.create(addon=self.addon, user=self.user, rating=4)
        self.refresh()
        assert self.get_bayesian_rating() == 4.0

    def test_edited(self):
        self.test_created()

        r = self.addon.reviews.all()[0]
        r.rating = 1
        r.save()
        self.refresh()

        assert self.get_bayesian_rating() == 2.5

    def test_deleted(self):
        self.test_created()

        r = self.addon.reviews.all()[0]
        r.delete()
        self.refresh()

        assert self.get_bayesian_rating() == 0.0
