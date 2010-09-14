from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import models

import bleach
from celeryutils import task
from tower import ugettext_lazy as _

import amo.models
from amo.urlresolvers import reverse
from translations.fields import TranslatedField
from users.models import UserProfile
from versions.models import Version


class ReviewManager(amo.models.ManagerBase):

    def get_query_set(self):
        qs = super(ReviewManager, self).get_query_set()
        return qs.transform(Review.transformer)

    def valid(self):
        """Get all reviews with rating > 0 that aren't replies."""
        return self.filter(reply_to=None, rating__gt=0)

    def latest(self):
        """Get all the latest valid reviews."""
        return self.valid().filter(is_latest=True)


class Review(amo.models.ModelBase):
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

    # Denormalized fields for easy lookup queries.
    # TODO: index on addon, user, latest
    is_latest = models.BooleanField(default=True, editable=False,
        help_text="Is this the user's latest review for the add-on?")
    previous_count = models.PositiveIntegerField(default=0, editable=False,
        help_text="How many previous reviews by the user for this add-on?")

    objects = ReviewManager()

    class Meta:
        db_table = 'reviews'
        ordering = ('-created',)

    def get_url_path(self):
        return reverse('reviews.detail', args=[self.addon_id, self.id])

    def flush_urls(self):
        urls = ['*/addon/%d/' % self.addon_id,
                '*/addon/%d/reviews/' % self.addon_id,
                '*/addon/%d/reviews/format:rss' % self.addon_id,
                '*/addon/%d/reviews/%d/' % (self.addon_id, self.id),
                '*/user/%d/' % self.user_id, ]
        return urls

    @classmethod
    def get_replies(cls, reviews):
        reviews = [r.id for r in reviews]
        qs = Review.objects.filter(reply_to__in=reviews)
        return dict((r.reply_to_id, r) for r in qs)

    @staticmethod
    def post_save(sender, instance, created, **kwargs):
        if created:
            Review.post_delete(sender, instance)
            # Avoid slave lag with the delay.
            check_spam.apply_async(args=[instance.id], countdown=600)

    @staticmethod
    def post_delete(sender, instance, **kwargs):
        from . import tasks
        pair = instance.addon_id, instance.user_id
        # Do this immediately so is_latest is correct. Use default to avoid
        # slave lag.
        tasks.update_denorm(pair, using='default')
        tasks.addon_review_aggregates.delay(instance.addon_id, using='default')

    @staticmethod
    def transformer(reviews):
        if not reviews:
            return

        # Attach users.
        user_ids = [r.user_id for r in reviews]
        users = UserProfile.objects.filter(id__in=user_ids)
        user_dict = dict((u.id, u) for u in users)
        for review in reviews:
            review.user = user_dict[review.user_id]

        # Attach versions.
        versions = dict((r.version_id, r) for r in reviews)
        for version in Version.objects.filter(id__in=versions.keys()):
            versions[version.id].version = version


models.signals.post_save.connect(Review.post_save, sender=Review)
models.signals.post_delete.connect(Review.post_delete, sender=Review)


# TODO: translate old flags.
class ReviewFlag(amo.models.ModelBase):
    SPAM = 'review_flag_reason_spam'
    LANGUAGE = 'review_flag_reason_language'
    SUPPORT = 'review_flag_reason_bug_support'
    OTHER = 'review_flag_reason_other'
    FLAGS = ((SPAM, _('Spam or otherwise non-review content')),
             (LANGUAGE, _('Inappropriate language/dialog')),
             (SUPPORT, _('Misplaced bug report or support request')),
             (OTHER, _('Other (please specify)')),
    )

    review = models.ForeignKey(Review)
    user = models.ForeignKey('users.UserProfile')
    flag = models.CharField(max_length=64, default=OTHER,
                            choices=FLAGS, db_column='flag_name')
    note = models.CharField(max_length=100, db_column='flag_notes', blank=True,
                           default='')

    class Meta:
        db_table = 'reviews_moderation_flags'
        unique_together = (('review', 'user'),)

    def flush_urls(self):
        return self.review.flush_urls()


class GroupedRating(object):
    """
    Group an add-on's ratings so we can have a graph of rating counts.

    SELECT rating, COUNT(rating) FROM reviews where addon=:id
    """
    # Non-critical data, so we always leave it in memcached.  Updated through
    # cron daily, so we cache for two days.

    @classmethod
    def key(cls, addon):
        return '%s:%s:%s' % (settings.CACHE_PREFIX, cls.__name__, addon)

    @classmethod
    def get(cls, addon):
        return cache.get(cls.key(addon))

    @classmethod
    def set(cls, addon, using=None):
        q = (Review.objects.latest().filter(addon=addon).using(using)
             .values_list('rating').annotate(models.Count('rating')))
        counts = dict(q)
        ratings = [(rating, counts.get(rating, 0)) for rating in range(1, 6)]
        two_days = 60 * 60 * 24 * 2
        cache.set(cls.key(addon), ratings, two_days)


class Spam(object):

    def __init__(self):
        from caching.invalidation import get_redis_backend
        self.redis = get_redis_backend()

    def add(self, review, reason):
        reason = 'amo:review:spam:%s' % reason
        self.redis.sadd(reason, review.id)
        self.redis.sadd('amo:review:spam:reasons', reason)

    def reasons(self):
        return self.redis.smembers('amo:review:spam:reasons')


@task
def check_spam(review_id):
    spam = Spam()
    review = Review.objects.using('default').get(id=review_id)
    thirty_days = datetime.now() - timedelta(days=30)
    others = (Review.objects.no_cache().exclude(id=review.id)
              .filter(user=review.user, created__gte=thirty_days))
    if len(others) > 10:
        spam.add(review, 'numbers')
    if bleach.url_re.search(review.body.localized_string):
        spam.add(review, 'urls')
    for other in others:
        if ((review.title and review.title == other.title)
            or review.body == other.body):
            spam.add(review, 'matches')
            break
