import re

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

import olympia.core.logger
from olympia import activity, amo, core
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import BaseQuerySet, ManagerBase, ModelBase
from olympia.amo.templatetags import jinja_helpers
from olympia.amo.utils import send_mail_jinja
from olympia.translations.templatetags.jinja_helpers import truncate


log = olympia.core.logger.getLogger('z.ratings')


class RatingQuerySet(BaseQuerySet):
    """
    A queryset modified for soft deletion.
    """

    def to_moderate(self):
        """Return ratings to moderate.

        Ratings attached lacking an addon or attached to an addon that is no
        longer nominated or public are ignored, as well as ratings attached to
        unlisted versions.
        """
        return self.exclude(
            Q(addon__isnull=True)
            | Q(version__channel=amo.CHANNEL_UNLISTED)
            | Q(ratingflag__isnull=True)
        ).filter(editorreview=True, addon__status__in=amo.VALID_ADDON_STATUSES)

    def update_ratings_and_addons_denormalized_fields(self, pairs):
        from olympia.addons.tasks import index_addons
        from olympia.ratings.tasks import addon_rating_aggregates, update_denorm

        update_denorm.delay(*pairs)
        addons = [pair[0] for pair in pairs]
        addon_rating_aggregates.delay(addons)
        index_addons.delay(addons)

    def delete(self):
        pairs = tuple(self.values_list('addon_id', 'user_id'))
        rval = self.order_by().update(deleted=F('id'))
        self.update_ratings_and_addons_denormalized_fields(pairs)
        return rval

    def undelete(self):
        pairs = tuple(self.values_list('addon_id', 'user_id'))
        rval = self.order_by().update(deleted=0)
        self.update_ratings_and_addons_denormalized_fields(pairs)
        return rval


class RatingManager(ManagerBase):
    _queryset_class = RatingQuerySet

    def __init__(self, include_deleted=False):
        # DO NOT change the default value of include_deleted unless you've read
        # through the comment just above the Addon managers
        # declaration/instantiation and understand the consequences.
        super().__init__()
        self.include_deleted = include_deleted

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.include_deleted:
            qs = qs.exclude(deleted__gt=0).exclude(reply_to__deleted__gt=0)
        return qs


class WithoutRepliesRatingManager(ManagerBase):
    """Manager to fetch ratings that aren't replies (and aren't deleted)."""

    _queryset_class = RatingQuerySet

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.exclude(deleted__gt=0)
        return qs.filter(reply_to__isnull=True)


class UnfilteredRatingManagerForRelations(RatingManager):
    """Like RatingManager, but defaults to include deleted objects.

    Designed to be used in reverse relations of Ratings like this:
    <Rating>.replies(manager='unfiltered_for_relations').all(), for when you
    want to use the related manager but need to include deleted replies.

    unfiltered_for_relations = UnfilteredRatingManagerForRelations() is
    defined in Rating for this to work.
    """

    def __init__(self, include_deleted=True):
        super().__init__(include_deleted=include_deleted)


class Rating(ModelBase):
    RATING_CHOICES = (
        (None, _('None')),
        (0, '☆☆☆☆☆'),
        (1, '☆☆☆☆★'),
        (2, '☆☆☆★★'),
        (3, '☆☆★★★'),
        (4, '☆★★★★'),
        (5, '★★★★★'),
    )
    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey(
        'addons.Addon', related_name='_ratings', on_delete=models.CASCADE
    )
    version = models.ForeignKey(
        'versions.Version', related_name='ratings', null=True, on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        'users.UserProfile', related_name='_ratings_all', on_delete=models.CASCADE
    )
    reply_to = models.ForeignKey(
        'self',
        null=True,
        related_name='replies',
        db_column='reply_to',
        on_delete=models.CASCADE,
    )

    rating = models.PositiveSmallIntegerField(null=True, choices=RATING_CHOICES)
    # Note that max_length isn't enforced at the database level for TextFields,
    # but the API serializer is set to obey it.
    body = models.TextField(
        blank=True, db_column='text_body', null=True, max_length=4000
    )
    ip_address = models.CharField(max_length=45, default='0.0.0.0')

    editorreview = models.BooleanField(default=False)
    flag = models.BooleanField(default=False)

    # Will be a non-zero (truthy) value when deleted, and 0 (falsely) when not deleted,
    # so assertions should work as expected. We're using an integer for the constraint.
    deleted = models.IntegerField(default=0)

    # Denormalized fields for easy lookup queries.
    is_latest = models.BooleanField(
        default=True,
        editable=False,
        help_text="Is this the user's latest rating for the add-on?",
    )
    previous_count = models.PositiveIntegerField(
        default=0,
        editable=False,
        help_text='How many previous ratings by the user for this add-on?',
    )

    unfiltered = RatingManager(include_deleted=True)
    objects = RatingManager()
    without_replies = WithoutRepliesRatingManager()
    unfiltered_for_relations = UnfilteredRatingManagerForRelations()

    class Meta:
        db_table = 'reviews'
        # This is very important: please read the lengthy comment in Addon.Meta
        # description
        base_manager_name = 'unfiltered'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=('version',), name='version_id'),
            models.Index(fields=('user',), name='reviews_ibfk_2'),
            models.Index(fields=('addon',), name='reviews_addon_idx'),
            models.Index(
                fields=('reply_to', 'is_latest', 'addon', 'created'),
                name='latest_reviews',
            ),
            models.Index(fields=('ip_address',), name='reviews_ip_address_057fddfa'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=('version', 'user', 'reply_to', 'deleted'),
                name='one_review_per_user',
            ),
        ]

    def __str__(self):
        return truncate(str(self.body), 10)

    @property
    def reply(self):
        # could be a deleted reply
        return self.replies(manager='unfiltered_for_relations').first()

    def get_url_path(self):
        return jinja_helpers.url('addons.ratings.detail', self.addon.slug, self.id)

    def approve(self):
        activity.log_create(
            amo.LOG.APPROVE_RATING,
            self.addon,
            self,
            details=dict(
                body=str(self.body),
                addon_id=self.addon.pk,
                addon_title=str(self.addon.name),
                is_flagged=self.ratingflag_set.exists(),
            ),
        )
        for flag in self.ratingflag_set.all():
            flag.delete()
        self.update(editorreview=False, _signal=False)

    def delete(self, *, skip_activity_log=False, clear_flags=True):
        current_user = core.get_user()
        # Log deleting ratings to moderation log, except if the rating user deletes it,
        # or skip_activty_log=True (sent when the addon is being deleted).
        if not (current_user == self.user or skip_activity_log):
            activity.log_create(
                amo.LOG.DELETE_RATING,
                self.addon,
                self,
                details={
                    'body': str(self.body),
                    'addon_id': self.addon.pk,
                    'addon_title': str(self.addon.name),
                    'is_flagged': self.ratingflag_set.exists(),
                },
            )
        if current_user != self.user and clear_flags:
            for flag in self.ratingflag_set.all():
                flag.delete()

        log.info(
            'Rating deleted: %s deleted id:%s by %s ("%s")',
            str(current_user),
            self.pk,
            str(self.user),
            str(self.body),
        )
        # a random integer would do, but using id makes sure it is unique.
        self.update(deleted=self.id)
        # Force refreshing of denormalized data (it wouldn't happen otherwise
        # because we're not dealing with a creation).
        self.update_denormalized_fields()

    def undelete(self, *, skip_activity_log=False):
        self.update(deleted=0, _signal=False)
        if not skip_activity_log:
            activity.log_create(amo.LOG.UNDELETE_RATING, self, self.addon)
        # We're avoiding triggering post_save signal normally because we don't
        # want to record an edit. We trigger the callback manually instead.
        rating_post_save(self.__class__, self, False, **{'undeleted': True})

    @classmethod
    def get_replies(cls, ratings):
        ratings = [r.id for r in ratings]
        qs = Rating.objects.filter(reply_to__in=ratings)
        return {r.reply_to_id: r for r in qs}

    def send_notification_email(self):
        if self.reply_to:
            # It's a reply.
            reply_url = jinja_helpers.url(
                'addons.ratings.detail',
                self.addon.slug,
                self.reply_to.pk,
                add_prefix=False,
            )
            data = {
                'name': self.addon.name,
                'reply': self.body,
                'rating_url': jinja_helpers.absolutify(reply_url),
            }
            recipients = [self.reply_to.user.email]
            subject = 'Mozilla Add-on Developer Reply: %s' % self.addon.name
            template = 'ratings/emails/reply_review.ltxt'
            perm_setting = 'reply'
        else:
            # It's a new rating.
            rating_url = jinja_helpers.url(
                'addons.ratings.detail', self.addon.slug, self.pk, add_prefix=False
            )
            data = {
                'name': self.addon.name,
                'rating': self,
                'rating_url': jinja_helpers.absolutify(rating_url),
            }
            recipients = [author.email for author in self.addon.authors.all()]
            subject = 'Mozilla Add-on User Rating: %s' % self.addon.name
            template = 'ratings/emails/new_rating.txt'
            perm_setting = 'new_review'
        send_mail_jinja(
            subject,
            template,
            data,
            recipient_list=recipients,
            perm_setting=perm_setting,
        )

    def update_denormalized_fields(self):
        from . import tasks

        pair = self.addon_id, self.user_id
        tasks.update_denorm.delay(pair)

    def post_save(sender, instance, created, **kwargs):
        from olympia.addons.models import update_search_index

        from . import tasks

        if kwargs.get('raw'):
            return

        undeleted = kwargs.get('undeleted')

        if not undeleted and not instance.deleted:
            action = 'New' if created else 'Edited'
            if instance.reply_to:
                log.info(f'{action} reply to {instance.reply_to_id}: {instance.pk}')
            else:
                log.info(f'{action} rating: {instance.pk}')

            # For new ratings, replies, and all edits by users we
            # want to insert a new ActivityLog.
            new_rating_or_edit = not instance.reply_to or not created
            if new_rating_or_edit:
                action = amo.LOG.ADD_RATING if created else amo.LOG.EDIT_RATING
                activity.log_create(action, instance.addon, instance)
            else:
                activity.log_create(amo.LOG.REPLY_RATING, instance.addon, instance)

            # For new ratings and new replies we want to send an email.
            if created:
                instance.send_notification_email()

        if created or undeleted:
            # Do this immediately synchronously so is_latest is correct before
            # we fire the aggregates task.
            instance.update_denormalized_fields()

        # Rating counts have changed, so run the task and trigger a reindex.
        tasks.addon_rating_aggregates.delay(instance.addon_id)
        update_search_index(instance.addon.__class__, instance.addon)


@receiver(models.signals.post_save, sender=Rating, dispatch_uid='rating_post_save')
def rating_post_save(sender, instance, created, **kwargs):
    # The extra indirection is to make it easy to mock and deactivate on a case
    # by case basis in tests despite the fact that it's already been connected.
    Rating.post_save(sender, instance, created, **kwargs)


class RatingFlag(ModelBase):
    SPAM = 'review_flag_reason_spam'
    LANGUAGE = 'review_flag_reason_language'
    SUPPORT = 'review_flag_reason_bug_support'
    AUTO_MATCH = 'review_flag_reason_auto_match'
    AUTO_RESTRICTION = 'review_flag_reason_auto_user_restriction'
    OTHER = 'review_flag_reason_other'
    USER_FLAGS = (
        (SPAM, _('Spam or otherwise non-review content')),
        (LANGUAGE, _('Inappropriate language/dialog')),
        (SUPPORT, _('Misplaced bug report or support request')),
        (OTHER, _('Other (please specify)')),
    )
    FLAGS = (
        *USER_FLAGS,
        (AUTO_MATCH, _('Auto-flagged due to word match')),
        (AUTO_RESTRICTION, _('Auto-flagged due to user restriction')),
    )

    rating = models.ForeignKey(Rating, db_column='review_id', on_delete=models.CASCADE)
    user = models.ForeignKey('users.UserProfile', null=True, on_delete=models.CASCADE)
    flag = models.CharField(
        max_length=64, default=OTHER, choices=FLAGS, db_column='flag_name'
    )
    note = models.CharField(
        max_length=100, db_column='flag_notes', blank=True, default=''
    )

    class Meta:
        db_table = 'reviews_moderation_flags'
        indexes = [
            models.Index(fields=('user',), name='index_user'),
            models.Index(fields=('rating',), name='index_review'),
            models.Index(fields=('modified',), name='index_modified'),
        ]
        constraints = [
            models.UniqueConstraint(fields=('rating', 'user'), name='index_review_user')
        ]


class RatingAggregate(ModelBase):
    addon = models.OneToOneField('addons.Addon', on_delete=models.CASCADE)
    count_1 = models.IntegerField(default=0, null=False)
    count_2 = models.IntegerField(default=0, null=False)
    count_3 = models.IntegerField(default=0, null=False)
    count_4 = models.IntegerField(default=0, null=False)
    count_5 = models.IntegerField(default=0, null=False)


DOT = '.'
ALPHANUMERIC_REGEX = r'[^\w]+|_+'


def word_validator(value):
    if DOT not in value and list(re.split(ALPHANUMERIC_REGEX, value)) != [value]:
        raise ValidationError(
            _('%(value)s contains a non-alphanumeric character.'),
            params={'value': value},
        )


class DeniedRatingWord(ModelBase):
    """Denied words in a rating body."""

    word = models.CharField(
        max_length=255,
        unique=True,
        help_text='Can only contain alphanumeric characters ("\\w", exc. "_"). '
        'If contains a "." it will be interpreted as a domain name instead, '
        'and can contain any character',
        validators=(word_validator,),
    )
    moderation = models.BooleanField(
        help_text='Flag for moderation rather than immediately deny.', default=False
    )

    CACHE_KEY = 'denied-rating-word:blocked'

    class Meta:
        db_table = 'reviews_denied_word'
        ordering = ('word', 'moderation')

    def __str__(self):
        return self.word

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @classmethod
    def blocked(cls, content, *, moderation):
        """
        Check to see if the content contains any of the (cached) list of denied words.
        Return the list of denied words (or an empty list if none are found).
        """
        if not content:
            return []
        content = content.lower()

        values = cls.objects.all().values_list('word', 'moderation')

        def fetch_names():
            return [(word.lower(), mod) for word, mod in values]

        blocked_list = cache.get_or_set(cls.CACHE_KEY, fetch_names)
        content_words = re.split(ALPHANUMERIC_REGEX, content)
        word_matches = (
            word
            for word, mod in blocked_list
            if mod == moderation and DOT not in word and word in content_words
        )
        domain_matches = (
            domain
            for domain, mod in blocked_list
            if mod == moderation and DOT in domain and domain in content
        )
        return [*word_matches, *domain_matches]
