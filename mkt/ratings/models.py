from django.db import models

import commonware.log
from tower import ugettext_lazy as _

import amo.models
from reviews.models import check_spam  # TODO: Port to memcache.
from translations.fields import TranslatedField
from users.models import UserProfile

log = commonware.log.getLogger('mkt.ratings')


class RatingManager(amo.models.ManagerBase):

    def valid(self):
        """Get all reviews that aren't replies."""
        # Use extra because Django wants to do a LEFT OUTER JOIN.
        return self.extra(where=['reply_to IS NULL'])

    def latest(self):
        """Get all the latest valid ratings."""
        return self.valid().filter(is_latest=True)


class Rating(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon', related_name='_ratings')
    user = models.ForeignKey('users.UserProfile', related_name='_ratings_all')
    reply_to = models.ForeignKey('self', null=True, unique=True,
                                 related_name='replies', db_column='reply_to')

    score = models.PositiveSmallIntegerField(null=True)
    body = TranslatedField(require_locale=False)
    ip_address = models.IPAddressField()

    editorreview = models.BooleanField(default=False)
    flag = models.BooleanField(default=False)

    # Denormalized fields for easy lookup queries.
    # TODO: index on addon, user, latest.
    is_latest = models.BooleanField(default=True, editable=False,
        help_text="Is this the user's latest review for the app?")
    previous_count = models.PositiveIntegerField(default=0, editable=False,
        help_text="How many previous reviews by the user for this app?")

    objects = RatingManager()

    class Meta:
        db_table = 'ratings'
        ordering = ('-created',)

    def get_url_path(self):
        return self.addon.get_ratings_url('detail', args=[self.id])

    def flush_urls(self):
        urls = ['*/app/%d/' % self.addon.app_slug,
                '*/app/%d/reviews/' % self.addon.app_slug,
                '*/app/%d/reviews/format:rss' % self.addon.app_slug,
                '*/app/%d/reviews/%d/' % (self.addon.app_slug, self.id),
                '*/user/%d/' % self.user_id]
        return urls

    @classmethod
    def get_replies(cls, reviews):
        reviews = [r.id for r in reviews]
        qs = Rating.objects.filter(reply_to__in=reviews)
        return dict((r.reply_to_id, r) for r in qs)

    @staticmethod
    def post_save(sender, instance, created, **kwargs):
        if kwargs.get('raw'):
            return
        if created:
            Rating.post_delete(sender, instance)
            # Avoid slave lag with the delay.
            check_spam.apply_async(args=[instance.id], countdown=600)

    @staticmethod
    def post_delete(sender, instance, **kwargs):
        if kwargs.get('raw'):
            return
        from . import tasks
        pair = instance.addon_id, instance.user_id
        # Do this immediately so is_latest is correct. Use default to avoid
        # slave lag.
        tasks.update_denorm(pair, using='default')
        tasks.addon_review_aggregates.delay(instance.addon_id, using='default')

    @staticmethod
    def transformer(reviews):
        user_ids = dict((r.user_id, r) for r in reviews)
        for user in UserProfile.uncached.filter(id__in=user_ids):
            user_ids[user.id].user = user


models.signals.post_save.connect(Rating.post_save, sender=Rating)
models.signals.post_delete.connect(Rating.post_delete, sender=Rating)


class RatingFlag(amo.models.ModelBase):
    SPAM = 'review_flag_reason_spam'
    LANGUAGE = 'review_flag_reason_language'
    SUPPORT = 'review_flag_reason_bug_support'
    OTHER = 'review_flag_reason_other'
    FLAGS = ((SPAM, _(u'Spam or otherwise non-review content')),
             (LANGUAGE, _(u'Inappropriate language/dialog')),
             (SUPPORT, _(u'Misplaced bug report or support request')),
             (OTHER, _(u'Other (please specify)')),
    )

    rating = models.ForeignKey(Rating)
    user = models.ForeignKey('users.UserProfile')
    flag = models.CharField(max_length=64, default=OTHER,
                            choices=FLAGS, db_column='flag_name')
    note = models.CharField(max_length=100, db_column='flag_notes', blank=True,
                            default='')

    class Meta:
        db_table = 'ratings_moderation_flags'
        unique_together = (('rating', 'user'),)

    def flush_urls(self):
        return self.rating.flush_urls()
