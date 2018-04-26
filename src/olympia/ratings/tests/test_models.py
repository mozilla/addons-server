# -*- coding: utf-8 -*-
from django.core import mail
from django.utils import translation

import mock

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.templatetags import jinja_helpers
from olympia.amo.tests import ESTestCase, TestCase, addon_factory, user_factory
from olympia.ratings import tasks
from olympia.ratings.models import GroupedRating, Rating, RatingFlag
from olympia.users.models import UserProfile


class TestRatingModel(TestCase):
    fixtures = ['ratings/test_models']

    def test_translations(self):
        translation.activate('en-US')

        # There's en-US and de translations.  We should get en-US.
        r1 = Rating.objects.get(id=1)
        self.trans_eq(r1.body, 'r1 body en', 'en-US')

        # There's only a de translation, so we get that.
        r2 = Rating.objects.get(id=2)
        self.trans_eq(r2.body, 'r2 body de', 'de')

        translation.activate('de')

        # en and de exist, we get de.
        r1 = Rating.objects.get(id=1)
        self.trans_eq(r1.body, 'r1 body de', 'de')

        # There's only a de translation, so we get that.
        r2 = Rating.objects.get(id=2)
        self.trans_eq(r2.body, 'r2 body de', 'de')

    def test_soft_delete(self):
        assert Rating.objects.count() == 2
        assert Rating.unfiltered.count() == 2

        Rating.objects.get(id=1).delete()

        assert Rating.objects.count() == 1
        assert Rating.without_replies.count() == 1
        assert Rating.unfiltered.count() == 2

        rating = Rating.objects.get(id=2)
        assert rating.previous_count == 0
        assert rating.is_latest is True

    @mock.patch('olympia.ratings.models.log')
    def test_soft_delete_user_responsible(self, log_mock):
        user_responsible = user_factory()
        rating = Rating.objects.get(id=1)
        rating.delete(user_responsible=user_responsible)
        assert log_mock.info.call_count == 1
        assert (log_mock.info.call_args[0][0] ==
                'Rating deleted: %s deleted id:%s by %s ("%s")')
        assert log_mock.info.call_args[0][1] == user_responsible.name
        assert log_mock.info.call_args[0][2] == rating.pk
        assert log_mock.info.call_args[0][3] == rating.user.name
        assert log_mock.info.call_args[0][4] == unicode(rating.body)

    def test_hard_delete(self):
        # Hard deletion is only for tests, but it's still useful to make sure
        # it's working properly.
        assert Rating.unfiltered.count() == 2
        Rating.objects.filter(id=1).delete(hard_delete=True)
        assert Rating.unfiltered.count() == 1
        assert Rating.objects.filter(id=2).exists()

    def test_undelete(self):
        self.test_soft_delete()
        deleted_rating = Rating.unfiltered.get(id=1)
        assert deleted_rating.deleted is True
        deleted_rating.undelete()

        # The deleted_review was the oldest, so loading the other one we should
        # see an updated previous_count, and is_latest should still be True.
        rating = Rating.objects.get(id=2)
        assert rating.previous_count == 1
        assert rating.is_latest is True

    def test_soft_delete_replies_are_hidden(self):
        rating = Rating.objects.get(pk=1)
        Rating.objects.create(
            addon=rating.addon, reply_to=rating,
            user=UserProfile.objects.all()[0])
        assert Rating.objects.count() == 3
        assert Rating.unfiltered.count() == 3
        assert Rating.without_replies.count() == 2

        Rating.objects.get(id=1).delete()

        # objects should only have 1 object, because we deleted the parent
        # review of the one we just created, so it should not be returned.
        assert Rating.objects.count() == 1

        # without_replies should also only have 1 object, because, because it
        # does not include replies anyway.
        assert Rating.without_replies.count() == 1

        # Unfiltered should have them all still.
        assert Rating.unfiltered.count() == 3

    @mock.patch('olympia.ratings.models.log')
    def test_author_delete(self, log_mock):
        rating = Rating.objects.get(pk=1)
        rating.delete(user_responsible=rating.user)

        rating.reload()
        assert ActivityLog.objects.count() == 0

    @mock.patch('olympia.ratings.models.log')
    def test_moderator_delete(self, log_mock):
        moderator = user_factory()
        rating = Rating.objects.get(pk=1)
        rating.update(editorreview=True)
        rating.ratingflag_set.create()
        rating.delete(user_responsible=moderator)

        rating.reload()
        assert ActivityLog.objects.count() == 1
        assert not rating.ratingflag_set.exists()

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.details == {
            'body': 'r1 body en',
            'is_flagged': True,
            'addon_title': 'my addon name',
            'addon_id': 4,
        }
        assert activity_log.user == moderator
        assert activity_log.action == amo.LOG.DELETE_RATING.id
        assert activity_log.arguments == [rating.addon, rating]

        assert log_mock.info.call_count == 1
        assert (log_mock.info.call_args[0][0] ==
                'Rating deleted: %s deleted id:%s by %s ("%s")')
        assert log_mock.info.call_args[0][1] == moderator.name
        assert log_mock.info.call_args[0][2] == rating.pk
        assert log_mock.info.call_args[0][3] == rating.user.name
        assert log_mock.info.call_args[0][4] == unicode(rating.body)

    def test_moderator_approve(self):
        moderator = user_factory()
        rating = Rating.objects.get(pk=1)
        rating.update(editorreview=True)
        rating.ratingflag_set.create()
        rating.approve(user=moderator)

        rating.reload()
        assert ActivityLog.objects.count() == 1
        assert not rating.ratingflag_set.exists()
        assert rating.editorreview is False

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.details == {
            'body': 'r1 body en',
            'is_flagged': True,
            'addon_title': 'my addon name',
            'addon_id': 4,
        }
        assert activity_log.user == moderator
        assert activity_log.action == amo.LOG.APPROVE_RATING.id
        assert activity_log.arguments == [rating.addon, rating]

    def test_filter_for_many_to_many(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        rating = Rating.objects.get(id=1)
        addon = rating.addon
        assert rating in addon._ratings.all()

        # Delete the review: it shouldn't be listed anymore.
        rating.delete()
        addon = Addon.objects.get(pk=addon.pk)
        assert rating not in addon._ratings.all()

    def test_no_filter_for_relations(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        rating = Rating.objects.get(id=1)
        flag = RatingFlag.objects.create(rating=rating,
                                         flag='review_flag_reason_spam')
        assert flag.rating == rating

        # Delete the review: <RatingFlag>.review should still work.
        rating.delete(user_responsible=rating.user)
        flag = RatingFlag.objects.get(pk=flag.pk)
        assert flag.rating == rating

    def test_creation_triggers_email_and_logging(self):
        addon = Addon.objects.get(pk=4)
        addon_author = addon.authors.first()
        review_user = user_factory()
        rating = Rating.objects.create(
            user=review_user, addon=addon,
            body=u'Rêviiiiiiew', user_responsible=review_user)

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == review_user
        assert activity_log.arguments == [addon, rating]
        assert activity_log.action == amo.LOG.ADD_RATING.id

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        rating_url = jinja_helpers.absolutify(
            jinja_helpers.url(
                'addons.ratings.detail', addon.slug, rating.pk,
                add_prefix=False))
        assert email.subject == 'Mozilla Add-on User Rating: my addon name'
        assert 'A user has rated your add-on,' in email.body
        assert 'my addon name' in email.body
        assert rating_url in email.body
        assert email.to == [addon_author.email]
        assert email.from_email == 'Mozilla Add-ons <nobody@mozilla.org>'

    def test_reply_triggers_email_but_no_logging(self):
        rating = Rating.objects.get(id=1)
        user = user_factory()
        Rating.objects.create(
            reply_to=rating, user=user, addon=rating.addon,
            body=u'Rêply', user_responsible=user)

        assert not ActivityLog.objects.exists()
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        reply_url = jinja_helpers.absolutify(
            jinja_helpers.url(
                'addons.ratings.detail', rating.addon.slug, rating.pk,
                add_prefix=False))
        assert email.subject == 'Mozilla Add-on Developer Reply: my addon name'
        assert 'A developer has replied to your review' in email.body
        assert 'add-on my addon name' in email.body
        assert reply_url in email.body
        assert email.to == ['arya@example.com']
        assert email.from_email == 'Mozilla Add-ons <nobody@mozilla.org>'

    def test_edit_triggers_logging_but_no_email(self):
        rating = Rating.objects.get(id=1)
        assert not ActivityLog.objects.exists()
        assert mail.outbox == []

        rating.user_responsible = rating.user
        rating.body = u'Editëd...'
        rating.save()

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == rating.user
        assert activity_log.arguments == [rating.addon, rating]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert mail.outbox == []

    def test_edit_reply_triggers_logging_but_no_email(self):
        rating = Rating.objects.get(id=1)
        reply = Rating.objects.create(
            reply_to=rating, user=user_factory(), addon=rating.addon)
        assert not ActivityLog.objects.exists()
        assert mail.outbox == []

        reply.user_responsible = reply.user
        reply.body = u'Actuälly...'
        reply.save()

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == reply.user
        assert activity_log.arguments == [reply.addon, reply]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert mail.outbox == []

    def test_non_user_edit_triggers_nothing(self):
        rating = Rating.objects.get(pk=1)
        rating.previous_count = 42
        rating.save()
        assert not ActivityLog.objects.exists()
        assert mail.outbox == []


class TestGroupedRating(TestCase):
    @classmethod
    # Prevent <Rating>.refresh() from being fired when setting up test data,
    # since it'd affect the results of our tests by calculating GroupedRating
    # results early (and storing result in cache) or changing is_latest boolean
    # on reviews.
    @mock.patch.object(Rating, 'refresh', lambda x, update_denorm=False: None)
    def setUpTestData(cls):
        cls.addon = addon_factory()
        user = user_factory()

        # Create a few ratings with various scores.
        rating = Rating.objects.create(addon=cls.addon, rating=3, user=user)
        Rating.objects.create(addon=cls.addon, rating=3, user=user_factory())
        Rating.objects.create(addon=cls.addon, rating=2, user=user_factory())
        Rating.objects.create(addon=cls.addon, rating=1, user=user_factory())
        Rating.objects.create(addon=cls.addon, rating=1, user=user_factory())
        Rating.objects.create(addon=cls.addon, rating=1, user=user_factory())

        # GroupedRating should ignore replies, so let's add one.
        Rating.objects.create(
            addon=cls.addon, rating=5, user=user_factory(), reply_to=rating)

        # GroupedRating should also ignore reviews that aren't the latest for
        # this user and addon, so let's add another one from the same user.
        Rating.objects.create(
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
        qs = Addon.search().filter(id=self.addon.id)
        return qs.values_dict('bayesian_rating')[0]['bayesian_rating']

    def test_created(self):
        assert self.get_bayesian_rating() == 0.0
        Rating.objects.create(addon=self.addon, user=self.user, rating=4)
        self.refresh()
        assert self.get_bayesian_rating() == 4.0

    def test_edited(self):
        self.test_created()

        rating = self.addon.ratings.all()[0]
        rating.rating = 1
        rating.save()
        self.refresh()

        assert self.get_bayesian_rating() == 2.5

    def test_deleted(self):
        self.test_created()

        rating = self.addon.ratings.all()[0]
        rating.delete()
        self.refresh()

        assert self.get_bayesian_rating() == 0.0
