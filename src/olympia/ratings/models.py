from django.core.cache import cache
from django.db import models
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _

import caching.base as caching

import olympia.core.logger
from olympia import activity, amo
from olympia.amo.templatetags import jinja_helpers
from olympia.amo.models import ManagerBase, ModelBase
from olympia.amo.utils import send_mail_jinja
from olympia.translations.fields import save_signal, TranslatedField
from olympia.translations.templatetags.jinja_helpers import truncate


log = olympia.core.logger.getLogger('z.ratings')


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


class WithoutRepliesReviewManager(ManagerBase):
    """Manager to fetch reviews that aren't replies (and aren't deleted)."""

    def get_queryset(self):
        qs = super(WithoutRepliesReviewManager, self).get_queryset()
        qs = qs._clone(klass=ReviewQuerySet)
        qs = qs.exclude(deleted=True)
        return qs.filter(reply_to__isnull=True)


class ReviewQuerySet(caching.CachingQuerySet):
    """
    A queryset modified for soft deletion.
    """
    def to_moderate(self):
        """Return reviews to moderate.

        Reviews attached lacking an addon or attached to an addon that is no
        longer nominated or public are ignored, as well as reviews attached to
        unlisted versions.
        """
        return self.exclude(
            Q(addon__isnull=True) |
            Q(version__channel=amo.RELEASE_CHANNEL_UNLISTED) |
            Q(reviewflag__isnull=True)).filter(
                editorreview=1, addon__status__in=amo.VALID_ADDON_STATUSES)

    def delete(self, user_responsible=None, hard_delete=False):
        if hard_delete:
            return super(ReviewQuerySet, self).delete()
        else:
            for review in self:
                review.delete(user_responsible=user_responsible)


class Review(ModelBase):
    addon = models.ForeignKey('addons.Addon', related_name='_reviews')
    version = models.ForeignKey('versions.Version', related_name='reviews',
                                null=True)
    user = models.ForeignKey('users.UserProfile', related_name='_reviews_all')
    reply_to = models.OneToOneField(
        'self', null=True, related_name='reply', db_column='reply_to')

    rating = models.PositiveSmallIntegerField(null=True)
    title = TranslatedField(require_locale=False)
    body = TranslatedField(require_locale=False)
    ip_address = models.CharField(max_length=255, default='0.0.0.0')

    editorreview = models.BooleanField(default=False)
    flag = models.BooleanField(default=False)

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
    without_replies = WithoutRepliesReviewManager()

    class Meta:
        db_table = 'reviews'
        ordering = ('-created',)

    def __unicode__(self):
        if self.title:
            return unicode(self.title)
        return truncate(unicode(self.body), 10)

    def __init__(self, *args, **kwargs):
        user_responsible = kwargs.pop('user_responsible', None)
        super(Review, self).__init__(*args, **kwargs)
        if user_responsible is not None:
            self.user_responsible = user_responsible

    def get_url_path(self):
        return jinja_helpers.url(
            'addons.ratings.detail', self.addon.slug, self.id)

    def approve(self, user):
        from olympia.reviewers.models import ReviewerScore

        activity.log_create(
            amo.LOG.APPROVE_REVIEW, self.addon, self, user=user, details=dict(
                title=unicode(self.title),
                body=unicode(self.body),
                addon_id=self.addon.pk,
                addon_title=unicode(self.addon.name),
                is_flagged=self.reviewflag_set.exists()))
        for flag in self.reviewflag_set.all():
            flag.delete()
        self.editorreview = False
        # We've already logged what we want to log, no need to pass
        # user_responsible=user.
        self.save()
        ReviewerScore.award_moderation_points(user, self.addon, self.pk)

    def delete(self, user_responsible=None):
        if user_responsible is None:
            user_responsible = self.user

        review_was_moderated = False
        # Log deleting reviews to moderation log,
        # except if the author deletes it
        if user_responsible != self.user:
            # Remember moderation state
            review_was_moderated = True
            from olympia.reviewers.models import ReviewerScore

            activity.log_create(
                amo.LOG.DELETE_REVIEW, self.addon, self, user=user_responsible,
                details=dict(
                    title=unicode(self.title),
                    body=unicode(self.body),
                    addon_id=self.addon.pk,
                    addon_title=unicode(self.addon.name),
                    is_flagged=self.reviewflag_set.exists()))
            for flag in self.reviewflag_set.all():
                flag.delete()

        log.info(u'Review deleted: %s deleted id:%s by %s ("%s": "%s")',
                 user_responsible.name, self.pk, self.user.name,
                 unicode(self.title), unicode(self.body))
        self.update(deleted=True)
        # Force refreshing of denormalized data (it wouldn't happen otherwise
        # because we're not dealing with a creation).
        self.update_denormalized_fields()

        if (review_was_moderated):
            ReviewerScore.award_moderation_points(user_responsible,
                                                  self.addon,
                                                  self.pk)

    def undelete(self):
        self.update(deleted=False)
        # Force refreshing of denormalized data (it wouldn't happen otherwise
        # because we're not dealing with a creation).
        self.update_denormalized_fields()

    @classmethod
    def get_replies(cls, reviews):
        reviews = [r.id for r in reviews]
        qs = Review.objects.filter(reply_to__in=reviews)
        return dict((r.reply_to_id, r) for r in qs)

    def send_notification_email(self):
        if self.reply_to:
            # It's a reply.
            reply_url = jinja_helpers.url(
                'addons.ratings.detail', self.addon.slug,
                self.reply_to.pk, add_prefix=False)
            data = {
                'name': self.addon.name,
                'reply_title': self.title,
                'reply': self.body,
                'reply_url': jinja_helpers.absolutify(reply_url)
            }
            recipients = [self.reply_to.user.email]
            subject = u'Mozilla Add-on Developer Reply: %s' % self.addon.name
            template = 'ratings/emails/reply_review.ltxt'
            perm_setting = 'reply'
        else:
            # It's a new review.
            reply_url = jinja_helpers.url(
                'addons.ratings.reply', self.addon.slug, self.pk,
                add_prefix=False)
            data = {
                'name': self.addon.name,
                'rating': '%s out of 5 stars' % self.rating,
                'review': self.body,
                'reply_url': jinja_helpers.absolutify(reply_url)
            }
            recipients = [author.email for author in self.addon.authors.all()]
            subject = u'Mozilla Add-on User Review: %s' % self.addon.name
            template = 'ratings/emails/add_review.ltxt'
            perm_setting = 'new_review'
        send_mail_jinja(
            subject, template, data,
            recipient_list=recipients, perm_setting=perm_setting)

    @staticmethod
    def post_save(sender, instance, created, **kwargs):
        if kwargs.get('raw'):
            return

        if hasattr(instance, 'user_responsible'):
            # user_responsible is not a field on the model, so it's not
            # persistent: it's just something the views will set temporarily
            # when manipulating a Review that indicates a real user made that
            # change.
            action = 'New' if created else 'Edited'
            if instance.reply_to:
                log.debug('%s reply to %s: %s' % (
                    action, instance.reply_to_id, instance.pk))
            else:
                log.debug('%s review: %s' % (action, instance.pk))

            # For new reviews - not replies - and all edits (including replies
            # this time) by users we want to insert a new ActivityLog.
            new_review_or_edit = not instance.reply_to or not created
            if new_review_or_edit:
                action = amo.LOG.ADD_REVIEW if created else amo.LOG.EDIT_REVIEW
                activity.log_create(action, instance.addon, instance,
                                    user=instance.user_responsible)

            # For new reviews and new replies we want to send an email.
            if created:
                instance.send_notification_email()

        instance.refresh(update_denorm=created)

    def refresh(self, update_denorm=False):
        from olympia.addons.models import update_search_index
        from . import tasks

        if update_denorm:
            # Do this immediately so is_latest is correct.
            self.update_denormalized_fields()

        # Review counts have changed, so run the task and trigger a reindex.
        tasks.addon_review_aggregates.delay(self.addon_id)
        update_search_index(self.addon.__class__, self.addon)

    def update_denormalized_fields(self):
        from . import tasks

        pair = self.addon_id, self.user_id
        tasks.update_denorm(pair)


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
        qs = (Review.without_replies.all().using(using)
              .filter(addon=addon, is_latest=True)
              .values_list('rating')
              .annotate(models.Count('rating')).order_by())
        counts = dict(qs)
        ratings = [(rating, counts.get(rating, 0)) for rating in range(1, 6)]
        cache.set(cls.key(addon), ratings)
        return ratings
