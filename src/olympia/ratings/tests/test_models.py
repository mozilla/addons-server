from unittest import mock

from django.core import mail
from django.core.exceptions import ValidationError

from elasticsearch.dsl import Q, Search

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import Addon
from olympia.amo.templatetags import jinja_helpers
from olympia.amo.tests import ESTestCase, TestCase, addon_factory, user_factory
from olympia.search.utils import get_es
from olympia.users.models import UserProfile

from ..models import DeniedRatingWord, Rating, RatingFlag


class TestRatingModel(TestCase):
    fixtures = ['ratings/test_models']

    def test_soft_delete(self):
        addon = Addon.objects.get()
        assert addon.average_rating == 0.0  # Hasn't been computed yet.

        assert Rating.objects.count() == 2
        assert Rating.unfiltered.count() == 2

        core.set_user(UserProfile.objects.all()[0])
        Rating.objects.get(id=1).delete()

        assert Rating.objects.count() == 1
        assert Rating.without_replies.count() == 1
        assert Rating.unfiltered.count() == 2

        rating = Rating.objects.get(id=2)
        assert rating.previous_count == 0
        assert rating.is_latest is True

        addon.reload()
        assert addon.average_rating == 4.0  # Has been computed after deletion.
        assert not ActivityLog.objects.filter(action=amo.LOG.DELETE_RATING.id).exists()

    def test_soft_delete_queryset(self):
        addon = Addon.objects.get()
        assert addon.average_rating == 0.0  # Hasn't been computed yet.

        assert Rating.objects.count() == 2
        assert Rating.unfiltered.count() == 2

        core.set_user(UserProfile.objects.all()[0])
        Rating.objects.filter(pk=1).delete()

        assert Rating.objects.count() == 1
        assert Rating.without_replies.count() == 1
        assert Rating.unfiltered.count() == 2

        rating = Rating.objects.get(id=2)
        assert rating.previous_count == 0
        assert rating.is_latest is True

        addon.reload()
        assert addon.average_rating == 4.0  # Has been computed after deletion.
        assert not ActivityLog.objects.filter(action=amo.LOG.DELETE_RATING.id).exists()

    @mock.patch('olympia.ratings.models.log')
    def test_soft_delete_by_different_user(self, log_mock):
        different_user = user_factory()
        core.set_user(different_user)
        rating = Rating.objects.get(id=1)
        rating.delete()
        assert log_mock.info.call_count == 1
        assert (
            log_mock.info.call_args[0][0]
            == 'Rating deleted: %s deleted id:%s by %s ("%s")'
        )
        assert log_mock.info.call_args[0][1] == str(different_user)
        assert log_mock.info.call_args[0][2] == rating.pk
        assert log_mock.info.call_args[0][3] == str(rating.user)
        assert log_mock.info.call_args[0][4] == str(rating.body)
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_RATING.id).exists()

    def test_soft_delete_by_different_user_skip_activty_log(self):
        different_user = user_factory()
        core.set_user(different_user)
        rating = Rating.objects.get(id=1)
        rating.delete(skip_activity_log=True)
        assert not ActivityLog.objects.filter(action=amo.LOG.DELETE_RATING.id).exists()

    def test_soft_delete_without_clearing_flags(self):
        rating = Rating.objects.get(id=1)
        RatingFlag.objects.create(rating=rating, flag='review_flag_reason_spam')
        assert Rating.objects.count() == 2
        assert rating.ratingflag_set.count() == 1

        rating.delete(clear_flags=False)

        assert Rating.objects.count() == 1
        rating.refresh_from_db()
        assert rating.ratingflag_set.count() == 1

    def test_soft_delete_with_clearing_flags(self):
        rating = Rating.objects.get(id=1)
        RatingFlag.objects.create(rating=rating, flag='review_flag_reason_spam')
        assert Rating.objects.count() == 2
        assert rating.ratingflag_set.count() == 1

        rating.delete(clear_flags=True)

        assert Rating.objects.count() == 1
        rating.refresh_from_db()
        assert rating.ratingflag_set.count() == 0

    def test_undelete(self):
        self.test_soft_delete()
        deleted_rating = Rating.unfiltered.get(id=1)
        assert deleted_rating.deleted != 0
        deleted_rating.undelete()

        # The deleted_review was the oldest, so loading the other one we should
        # see an updated previous_count, and is_latest should still be True.
        rating = Rating.objects.get(id=2)
        assert rating.previous_count == 1
        assert rating.is_latest is True

    def test_soft_delete_replies_are_hidden(self):
        rating = Rating.objects.get(pk=1)
        user = UserProfile.objects.all()[0]
        core.set_user(user)
        Rating.objects.create(addon=rating.addon, reply_to=rating, user=user)
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
        core.set_user(rating.user)
        rating.delete()

        rating.reload()
        assert ActivityLog.objects.count() == 0

    @mock.patch('olympia.ratings.models.log')
    def test_moderator_delete(self, log_mock):
        moderator = user_factory()
        rating = Rating.objects.get(pk=1)
        rating.update(editorreview=True, _signal=False)
        rating.ratingflag_set.create()
        core.set_user(moderator)
        rating.delete()

        rating.reload()
        assert ActivityLog.objects.count() == 1
        assert not rating.ratingflag_set.exists()

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.details == {
            'body': 'r1 body',
            'is_flagged': True,
            'addon_title': 'my addon name',
            'addon_id': 4,
        }
        assert activity_log.user == moderator
        assert activity_log.action == amo.LOG.DELETE_RATING.id
        assert activity_log.arguments == [rating.addon, rating]

        assert log_mock.info.call_count == 1
        assert (
            log_mock.info.call_args[0][0]
            == 'Rating deleted: %s deleted id:%s by %s ("%s")'
        )
        assert log_mock.info.call_args[0][1] == str(moderator)
        assert log_mock.info.call_args[0][2] == rating.pk
        assert log_mock.info.call_args[0][3] == str(rating.user)
        assert log_mock.info.call_args[0][4] == str(rating.body)

    def test_moderator_approve(self):
        moderator = user_factory()
        rating = Rating.objects.get(pk=1)
        rating.update(editorreview=True, _signal=False)
        rating.ratingflag_set.create()
        core.set_user(moderator)
        rating.approve()

        rating.reload()
        assert ActivityLog.objects.count() == 1
        assert not rating.ratingflag_set.exists()
        assert rating.editorreview is False

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.details == {
            'body': 'r1 body',
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
        core.set_user(rating.user)
        rating.delete()
        addon = Addon.objects.get(pk=addon.pk)
        assert rating not in addon._ratings.all()

    def test_no_filter_for_relations(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        rating = Rating.objects.get(id=1)
        flag = RatingFlag.objects.create(rating=rating, flag='review_flag_reason_spam')
        assert flag.rating == rating

        # Delete the review: <RatingFlag>.review should still work.
        core.set_user(rating.user)
        rating.delete()
        flag = RatingFlag.objects.get(pk=flag.pk)
        assert flag.rating == rating

    def test_creation_triggers_email_and_logging(self):
        addon = Addon.objects.get(pk=4)
        addon_author = addon.authors.first()
        review_user = user_factory()
        core.set_user(review_user)
        rating = Rating.objects.create(
            user=review_user,
            addon=addon,
            body='Rêviiiiiiew',
        )

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == review_user
        assert activity_log.arguments == [addon, rating]
        assert activity_log.action == amo.LOG.ADD_RATING.id

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        rating_url = jinja_helpers.absolutify(
            jinja_helpers.url(
                'addons.ratings.detail', addon.slug, rating.pk, add_prefix=False
            )
        )
        assert email.subject == 'Mozilla Add-on User Rating: my addon name'
        assert 'A user has rated your add-on,' in email.body
        assert 'my addon name' in email.body
        assert rating_url in email.body
        assert email.to == [addon_author.email]
        assert email.from_email == 'Mozilla Add-ons <nobody@mozilla.org>'

    def test_reply_triggers_email_and_logging(self):
        rating = Rating.objects.get(id=1)
        user = user_factory()
        core.set_user(user)
        Rating.objects.create(
            reply_to=rating,
            user=user,
            addon=rating.addon,
            body='Rêply',
        )

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == user
        assert activity_log.arguments == [rating.addon, rating.reply]
        assert activity_log.action == amo.LOG.REPLY_RATING.id

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        reply_url = jinja_helpers.absolutify(
            jinja_helpers.url(
                'addons.ratings.detail', rating.addon.slug, rating.pk, add_prefix=False
            )
        )
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

        core.set_user(rating.user)
        rating.body = 'Editëd...'
        rating.save()

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == rating.user
        assert activity_log.arguments == [rating.addon, rating]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert mail.outbox == []

    def test_edit_reply_triggers_logging_but_no_email(self):
        rating = Rating.objects.get(id=1)
        user = user_factory()
        core.set_user(user)
        reply = Rating.objects.create(reply_to=rating, user=user, addon=rating.addon)
        assert len(mail.outbox) == 1
        mail.outbox = []  # Clear email sent at creation.

        reply.body = 'Actuälly...'
        reply.save()

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.user == user
        assert activity_log.arguments == [reply.addon, reply]
        assert activity_log.action == amo.LOG.EDIT_RATING.id

        assert mail.outbox == []

    def test_non_user_edit_triggers_nothing(self):
        rating = Rating.objects.get(pk=1)
        rating.previous_count = 42
        rating.save()
        assert not ActivityLog.objects.exists()
        assert mail.outbox == []

    def test_reply_property(self):
        rating = Rating.objects.get(pk=1)
        user = user_factory()
        assert rating.replies.all().count() == 0
        assert rating.reply_to is None

        # add some replies
        deleted_rating = Rating.objects.create(
            reply_to=rating,
            user=user,
            addon=rating.addon,
            version=rating.addon.current_version,
            deleted=123,
        )
        assert rating.reload().reply == deleted_rating
        not_deleted_reply = Rating.objects.create(
            reply_to=rating,
            user=user,
            addon=rating.addon,
            version=rating.addon.current_version,
        )
        assert rating.reload().reply == not_deleted_reply


class TestRefreshTest(ESTestCase):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.addon = addon_factory()
        self.user = UserProfile.objects.all()[0]
        self.refresh()
        core.set_user(self.user)

        assert self.get_bayesian_rating() == 0.0

    def get_bayesian_rating(self):
        qs = Search(using=get_es(), index=AddonIndexer.get_index_alias()).filter(
            Q('term', id=self.addon.pk)
        )
        return qs.execute()[0]['bayesian_rating']

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


class TestDeniedRatingWord(TestCase):
    def test_blocked(self):
        DeniedRatingWord.objects.create(word='FOO', moderation=False)
        DeniedRatingWord.objects.create(word='baa', moderation=False)
        DeniedRatingWord.objects.create(word='hMm', moderation=True)
        DeniedRatingWord.objects.create(word='mmm', moderation=True)

        with self.assertNumQueries(1):
            text = 'text with ,foo_ inside mmmm'
            assert DeniedRatingWord.blocked(text, moderation=True) == []
            assert DeniedRatingWord.blocked(text, moderation=False) == ['foo']

        with self.assertNumQueries(0):
            text = 'BAA! with Hmm:mmm mmm'
            assert DeniedRatingWord.blocked(text, moderation=True) == ['hmm', 'mmm']
            assert DeniedRatingWord.blocked(text, moderation=False) == ['baa']

        assert DeniedRatingWord.blocked('foobar', moderation=False) == []
        for sep in ('.', ',', '-', '_', ':', ';', ' '):
            assert DeniedRatingWord.blocked(f'foo{sep}bar', moderation=False) == ['foo']
            assert DeniedRatingWord.blocked(f'foo{sep}bar', moderation=True) == []
            assert DeniedRatingWord.blocked(f'mmm{sep}bar', moderation=False) == []
            assert DeniedRatingWord.blocked(f'mmm{sep}bar', moderation=True) == ['mmm']

    def test_blocked_domains(self):
        DeniedRatingWord.objects.create(word='FOO.bar', moderation=False)
        DeniedRatingWord.objects.create(word='www.hMm.com', moderation=True)

        non_mod_contents = [
            'bazfoo.bar',
            'foo.bar.baz',
            'foo.barbaz',
            'foo.bar.',
        ]
        mod_contents = [
            'wwwwww.hmm.com',
            'www.hmm.com.baz',
            'www.hmm.comcom',
            'www.hmm.com.',
        ]
        for content in non_mod_contents:
            assert DeniedRatingWord.blocked(content, moderation=True) == []
            assert DeniedRatingWord.blocked(content, moderation=False) == ['foo.bar']

        for content in mod_contents:
            assert DeniedRatingWord.blocked(content, moderation=True) == ['www.hmm.com']
            assert DeniedRatingWord.blocked(content, moderation=False) == []

        for sep in (',', '-', '_', ':', ';', ' ', ''):
            assert DeniedRatingWord.blocked(f'foo{sep}bar', moderation=False) == []
            assert DeniedRatingWord.blocked(f'foo{sep}bar', moderation=True) == []
            assert (
                DeniedRatingWord.blocked(f'www{sep}hmm{sep}com', moderation=False) == []
            )
            assert (
                DeniedRatingWord.blocked(f'www{sep}hmm{sep}com', moderation=True) == []
            )

    def test_cache_clears_on_save(self):
        DeniedRatingWord.objects.create(word='FOO')
        with self.assertNumQueries(1):
            DeniedRatingWord.blocked('dfdfdf', moderation=False)
            DeniedRatingWord.blocked('45goih', moderation=False)
        DeniedRatingWord.objects.create(word='baa')
        with self.assertNumQueries(1):
            DeniedRatingWord.blocked('446kjsd', moderation=False)
            DeniedRatingWord.blocked('ddv 989', moderation=False)

    def test_word_validation(self):
        for word in ('yes', 'foo.baa'):
            DeniedRatingWord(word=word).full_clean()  # would raise

        for word in ('sp ace', 'comma,', 'un_der', '-dash'):
            with self.assertRaises(ValidationError):
                DeniedRatingWord(word=word).full_clean()
