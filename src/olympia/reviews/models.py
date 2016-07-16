from datetime import datetime, timedelta
import logging

from django.core.cache import cache
from django.db import models
from django.utils.translation import ugettext_lazy as _

import bleach
import caching.base as caching

from olympia.amo.models import ManagerBase, ModelBase
from olympia.amo import helpers
from olympia.amo.celery import task
from olympia.translations.fields import save_signal, TranslatedField
from olympia.users.models import UserProfile

log = logging.getLogger('z.review')


class ReviewManager(ManagerBase):

    def __init__(self, include_deleted=False):
        # DO NOT change the default value of include_deleted unless you've read
        # through the comment just above the Addon managers
        # declaration/instantiation and understand the consequences.
        super(ReviewManager, self).__init__()
        self.include_deleted = include_deleted

    def get_queryset(self):
        qs = super(ReviewManager, self).get_queryset()
        qs = qs._clone(klass=ReviewQuerySet)
        if not self.include_deleted:
            qs = qs.exclude(deleted=True).exclude(reply_to__deleted=True)
        return qs

    def valid(self):
        """Get all reviews that aren't replies."""
        return self.filter(reply_to__isnull=True)


class ReviewQuerySet(caching.CachingQuerySet):
    """
    A queryset modified for soft deletion.
    """

    def delete(self):
        for review in self:
            review.delete()


class Review(ModelBase):
    addon = models.ForeignKey('addons.Addon', related_name='_reviews')
    version = models.ForeignKey('versions.Version', related_name='reviews',
                                null=True)
    user = models.ForeignKey('users.UserProfile', related_name='_reviews_all')
    reply_to = models.ForeignKey('self', null=True, unique=True,
                                 related_name='replies', db_column='reply_to')

    rating = models.PositiveSmallIntegerField(null=True)
    title = TranslatedField(require_locale=False)
    body = TranslatedField(require_locale=False)
    ip_address = models.CharField(max_length=255, default='0.0.0.0')

    editorreview = models.BooleanField(default=False)
    flag = models.BooleanField(default=False)
    sandbox = models.BooleanField(default=False)
    client_data = models.ForeignKey('stats.ClientData', null=True, blank=True)

    deleted = models.BooleanField(default=False)

    # Denormalized fields for easy lookup queries.
    # TODO: index on addon, user, latest
    is_latest = models.BooleanField(
        default=True, editable=False,
        help_text="Is this the user's latest review for the add-on?")
    previous_count = models.PositiveIntegerField(
        default=0, editable=False,
        help_text="How many previous reviews by the user for this add-on?")

    # The order of those managers is very important: please read the lengthy
    # comment above the Addon managers declaration/instantiation.
    unfiltered = ReviewManager(include_deleted=True)
    objects = ReviewManager()

    class Meta:
        db_table = 'reviews'
        ordering = ('-created',)

    def get_url_path(self):
        return helpers.url('addons.reviews.detail', self.addon.slug, self.id)

    def delete(self):
        self.update(deleted=True)
        # This should happen in the `post_save` hook.
        # self.refresh(update_denorm=True)

    def undelete(self):
        self.update(deleted=False)
        # This should happen in the `post_save` hook.
        # self.refresh(update_denorm=True)

    @classmethod
    def get_replies(cls, reviews):
        reviews = [r.id for r in reviews]
        qs = Review.objects.filter(reply_to__in=reviews)
        return dict((r.reply_to_id, r) for r in qs)

    @staticmethod
    def post_save(sender, instance, created, **kwargs):
        if kwargs.get('raw'):
            return
        instance.refresh(update_denorm=created)
        if created:
            # Avoid slave lag with the delay.
            check_spam.apply_async(args=[instance.id], countdown=600)

    def refresh(self, update_denorm=False):
        from olympia.addons.models import update_search_index
        from . import tasks

        if update_denorm:
            pair = self.addon_id, self.user_id
            # Do this immediately so is_latest is correct. Use default
            # to avoid slave lag.
            tasks.update_denorm(pair, using='default')

        # Review counts have changed, so run the task and trigger a reindex.
        tasks.addon_review_aggregates.delay(self.addon_id, using='default')
        update_search_index(self.addon.__class__, self.addon)

    @staticmethod
    def transformer(reviews):
        user_ids = dict((r.user_id, r) for r in reviews)
        for user in UserProfile.objects.no_cache().filter(id__in=user_ids):
            user_ids[user.id].user = user


models.signals.post_save.connect(Review.post_save, sender=Review,
                                 dispatch_uid='review_post_save')
models.signals.pre_save.connect(save_signal, sender=Review,
                                dispatch_uid='review_translations')


# TODO: translate old flags.
class ReviewFlag(ModelBase):
    SPAM = 'review_flag_reason_spam'
    LANGUAGE = 'review_flag_reason_language'
    SUPPORT = 'review_flag_reason_bug_support'
    OTHER = 'review_flag_reason_other'
    FLAGS = (
        (SPAM, _(u'Spam or otherwise non-review content')),
        (LANGUAGE, _(u'Inappropriate language/dialog')),
        (SUPPORT, _(u'Misplaced bug report or support request')),
        (OTHER, _(u'Other (please specify)')),
    )

    review = models.ForeignKey(Review)
    user = models.ForeignKey('users.UserProfile', null=True)
    flag = models.CharField(max_length=64, default=OTHER,
                            choices=FLAGS, db_column='flag_name')
    note = models.CharField(max_length=100, db_column='flag_notes', blank=True,
                            default='')

    class Meta:
        db_table = 'reviews_moderation_flags'
        unique_together = (('review', 'user'),)


class GroupedRating(object):
    """
    Group an add-on's ratings so we can have a graph of rating counts.

    SELECT rating, COUNT(rating) FROM reviews where addon=:id
    """
    # Non-critical data, so we always leave it in memcache. Numbers are updated
    # when a new review comes in.
    prefix = 'addons:grouped:rating'

    @classmethod
    def key(cls, addon):
        return '%s:%s' % (cls.prefix, addon)

    @classmethod
    def get(cls, addon, update_none=True):
        try:
            grouped_ratings = cache.get(cls.key(addon))
            if update_none and grouped_ratings is None:
                return cls.set(addon)
            return grouped_ratings
        except Exception:
            # Don't worry about failures, especially timeouts.
            return

    @classmethod
    def set(cls, addon, using=None):
        q = (Review.objects.valid().using(using)
             .filter(addon=addon, is_latest=True)
             .values_list('rating')
             .annotate(models.Count('rating')))
        counts = dict(q)
        ratings = [(rating, counts.get(rating, 0)) for rating in range(1, 6)]
        cache.set(cls.key(addon), ratings)
        return ratings


class Spam(object):

    def add(self, review, reason):
        reason = 'amo:review:spam:%s' % reason
        try:
            reasonset = cache.get('amo:review:spam:reasons', set())
        except KeyError:
            reasonset = set()
        try:
            idset = cache.get(reason, set())
        except KeyError:
            idset = set()
        reasonset.add(reason)
        cache.set('amo:review:spam:reasons', reasonset)
        idset.add(review.id)
        cache.set(reason, idset)
        return True

    def reasons(self):
        return cache.get('amo:review:spam:reasons')


@task
def check_spam(review_id, **kw):
    spam = Spam()
    try:
        review = Review.objects.using('default').get(id=review_id)
    except Review.DoesNotExist:
        log.error('Review does not exist, check spam for review_id: %s'
                  % review_id)
        return

    thirty_days = datetime.now() - timedelta(days=30)
    others = (Review.objects.no_cache().exclude(id=review.id)
              .filter(user=review.user, created__gte=thirty_days))
    if len(others) > 10:
        spam.add(review, 'numbers')
    if (review.body is not None and
            bleach.url_re.search(review.body.localized_string)):
        spam.add(review, 'urls')
    for other in others:
        if ((review.title and review.title == other.title) or
                review.body == other.body):
            spam.add(review, 'matches')
            break
