import itertools

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils import translation

from tower import ugettext_lazy as _

import amo.models
from translations.fields import TranslatedField
from translations.models import Translation
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
    title = TranslatedField()
    body = TranslatedField()
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

    def flush_urls(self):
        urls = ['*/addon/%d/' % self.addon_id,
                '*/addon/%d/reviews/' % self.addon_id,
                '*/addon/%d/reviews/format:rss' % self.addon_id,
                '*/addon/%d/reviews/%d/' % (self.addon_id, self.id),
                '*/user/%d/' % self.user.id, ]
        return urls

    @classmethod
    def fetch_translations(cls, ids, lang):
        if not ids:
            return []

        rv = {}
        ts = Translation.objects.filter(id__in=ids)

        # If a translation exists for the current language, use it.  Otherwise,
        # make do with whatever is available.  (Reviewers only write reviews in
        # their language).
        for id, translations in itertools.groupby(ts, lambda t: t.id):
            locales = dict((t.locale, t) for t in translations)
            if lang in locales:
                rv[id] = locales[lang]
            else:
                rv[id] = locales.itervalues().next()

        return rv.values()

    @staticmethod
    def post_save(sender, instance, created, **kwargs):
        if created:
            Review.post_delete(sender, instance)

    @staticmethod
    def post_delete(sender, instance, **kwargs):
        from . import tasks
        pair = instance.addon_id, instance.user_id
        # Do this immediately so is_latest is correct.
        tasks.update_denorm(pair)
        tasks.addon_review_aggregates.delay(instance.addon_id)

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

        # Attach translations. Some of these will be picked up by the
        # Translation transformer, but reviews have special requirements
        # (see fetch_translations).
        names = dict((f.attname, f.name)
                     for f in Review._meta.translated_fields)
        ids, trans = {}, {}
        for review in reviews:
            for attname, name in names.items():
                trans_id = getattr(review, attname)
                if getattr(review, name) is None and trans_id is not None:
                    ids[trans_id] = attname
                    trans[trans_id] = review
        translations = Review.fetch_translations(trans.keys(),
                                                 translation.get_language())
        for t in translations:
            setattr(trans[t.id], names[ids[t.id]], t)

        # Attach versions.
        versions = dict((r.version_id, r) for r in reviews)
        for version in Version.objects.filter(id__in=versions.keys()):
            versions[version.id].version = version


models.signals.post_save.connect(Review.post_save, sender=Review)
models.signals.post_delete.connect(Review.post_delete, sender=Review)


# TODO: translate old flags.
class ReviewFlag(amo.models.ModelBase):
    FLAGS = (
        ('spam', _('Spam or otherwise non-review content')),
        ('language', _('Inappropriate language/dialog')),
        ('bug_support', _('Misplaced bug report or support request')),
        ('other', _('Other (please specify)')),
    )

    review = models.ForeignKey(Review)
    user = models.ForeignKey('users.UserProfile')
    flag = models.CharField(max_length=64, default='other',
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
    def set(cls, addon):
        q = (Review.objects.valid().filter(addon=addon)
             .values_list('rating').annotate(models.Count('rating')))
        counts = dict(q)
        ratings = [(rating, counts.get(rating, 0)) for rating in range(1, 6)]
        two_days = 60 * 60 * 24 * 2
        cache.set(cls.key(addon), ratings, two_days)
