import json
import string
import uuid

from collections import defaultdict
from copy import copy
from datetime import datetime

from django.apps import apps
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import ugettext

import jinja2

import olympia.core.logger

from olympia import amo, constants
from olympia.access.models import Group
from olympia.addons.models import Addon
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import BaseQuerySet, ManagerBase, ModelBase
from olympia.bandwagon.models import Collection
from olympia.blocklist.models import Block
from olympia.files.models import File
from olympia.ratings.models import Rating
from olympia.reviewers.models import CannedResponse
from olympia.tags.models import Tag
from olympia.users.models import UserProfile
from olympia.users.templatetags.jinja_helpers import user_link
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.amo.activity')

# Number of times a token can be used.
MAX_TOKEN_USE_COUNT = 100


class ActivityLogToken(ModelBase):
    id = PositiveAutoField(primary_key=True)
    version = models.ForeignKey(
        Version, related_name='token', on_delete=models.CASCADE)
    user = models.ForeignKey(
        'users.UserProfile', related_name='activity_log_tokens',
        on_delete=models.CASCADE)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True)
    use_count = models.IntegerField(
        default=0,
        help_text='Stores the number of times the token has been used')

    class Meta:
        db_table = 'log_activity_tokens'
        constraints = [
            models.UniqueConstraint(fields=('version', 'user'),
                                    name='version_id'),
        ]

    def is_expired(self):
        return self.use_count >= MAX_TOKEN_USE_COUNT

    def is_valid(self):
        return (not self.is_expired() and
                self.version == self.version.addon.find_latest_version(
                    channel=self.version.channel, exclude=()))

    def expire(self):
        self.update(use_count=MAX_TOKEN_USE_COUNT)

    def increment_use(self):
        self.__class__.objects.filter(pk=self.pk).update(
            use_count=models.expressions.F('use_count') + 1)
        self.use_count = self.use_count + 1


class ActivityLogEmails(ModelBase):
    """A log of message ids of incoming emails so we don't duplicate process
    them."""
    messageid = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'log_activity_emails'


class AddonLog(ModelBase):
    """
    This table is for indexing the activity log by addon.
    """
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    activity_log = models.ForeignKey('ActivityLog', on_delete=models.CASCADE)

    class Meta:
        db_table = 'log_activity_addon'
        ordering = ('-created',)

    def transfer(self, new_addon):
        try:
            # arguments is a structure:
            # ``arguments = [{'addons.addon':12}, {'addons.addon':1}, ... ]``
            arguments = json.loads(self.activity_log._arguments)
        except Exception:
            log.info('unserializing data from addon_log failed: %s' %
                     self.activity_log.id)
            return None

        new_arguments = []
        for item in arguments:
            if item.get('addons.addon', 0) == self.addon.id:
                new_arguments.append({'addons.addon': new_addon.id})
            else:
                new_arguments.append(item)

        self.activity_log.update(_arguments=json.dumps(new_arguments))
        self.update(addon=new_addon)


class CommentLog(ModelBase):
    """
    This table is for indexing the activity log by comment.
    """
    activity_log = models.ForeignKey('ActivityLog', on_delete=models.CASCADE)
    comments = models.TextField()

    class Meta:
        db_table = 'log_activity_comment'
        ordering = ('-created',)


class VersionLog(ModelBase):
    """
    This table is for indexing the activity log by version.
    """
    activity_log = models.ForeignKey('ActivityLog', on_delete=models.CASCADE)
    version = models.ForeignKey(Version, on_delete=models.CASCADE)

    class Meta:
        db_table = 'log_activity_version'
        ordering = ('-created',)


class UserLog(ModelBase):
    """
    This table is for indexing the activity log by user.
    Note: This includes activity performed unto the user.
    """
    activity_log = models.ForeignKey('ActivityLog', on_delete=models.CASCADE)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)

    class Meta:
        db_table = 'log_activity_user'
        ordering = ('-created',)


class GroupLog(ModelBase):
    """
    This table is for indexing the activity log by access group.
    """
    id = PositiveAutoField(primary_key=True)
    activity_log = models.ForeignKey('ActivityLog', on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)

    class Meta:
        db_table = 'log_activity_group'
        ordering = ('-created',)


class BlockLog(ModelBase):
    """
    This table is for indexing the activity log by Blocklist Block.
    """
    id = PositiveAutoField(primary_key=True)
    activity_log = models.ForeignKey('ActivityLog', on_delete=models.CASCADE)
    block = models.ForeignKey(Block, on_delete=models.SET_NULL, null=True)
    guid = models.CharField(max_length=255, null=False)

    class Meta:
        db_table = 'log_activity_block'
        ordering = ('-created',)


class DraftComment(ModelBase):
    """A model that allows us to draft comments for reviews before we have
    an ActivityLog instance ready.

    This is being used by the commenting API by the code-manager.
    """
    id = PositiveAutoField(primary_key=True)
    version = models.ForeignKey(Version, on_delete=models.CASCADE)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    filename = models.CharField(max_length=255, null=True, blank=True)
    lineno = models.PositiveIntegerField(null=True)
    canned_response = models.ForeignKey(
        CannedResponse, null=True, default=None,
        on_delete=models.SET_DEFAULT)
    comment = models.TextField(blank=True)

    class Meta:
        db_table = 'log_activity_comment_draft'


class ActivityLogQuerySet(BaseQuerySet):
    def default_transformer(self, logs):
        ActivityLog.arguments_builder(logs)


class ActivityLogManager(ManagerBase):
    _queryset_class = ActivityLogQuerySet

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.transform(qs.default_transformer).prefetch_related('user')
        return qs

    def for_addons(self, addons):
        if isinstance(addons, Addon):
            addons = (addons,)

        return self.filter(addonlog__addon__in=addons)

    def for_versions(self, versions):
        if isinstance(versions, Version):
            versions = (versions,)

        return self.filter(versionlog__version__in=versions)

    def for_groups(self, groups):
        if isinstance(groups, Group):
            groups = (groups,)

        return self.filter(grouplog__group__in=groups)

    def for_user(self, user):
        return self.filter(userlog__user=user)

    def for_block(self, block):
        return self.filter(blocklog__block=block)

    def for_guidblock(self, guid):
        return self.filter(blocklog__guid=guid)

    def for_developer(self):
        return self.exclude(action__in=constants.activity.LOG_ADMINS +
                            constants.activity.LOG_HIDE_DEVELOPER)

    def admin_events(self):
        return self.filter(action__in=constants.activity.LOG_ADMINS)

    def moderation_events(self):
        return self.filter(action__in=constants.activity.LOG_RATING_MODERATION)

    def review_queue(self):
        qs = self._by_type()
        return (qs.filter(action__in=constants.activity.LOG_REVIEW_QUEUE)
                  .exclude(user__id=settings.TASK_USER_ID))

    def review_log(self):
        qs = self._by_type()
        return (
            qs.filter(action__in=constants.activity.LOG_REVIEWER_REVIEW_ACTION)
            .exclude(user__id=settings.TASK_USER_ID))

    def total_ratings(self, theme=False):
        """Return the top users, and their # of reviews."""
        qs = self._by_type()
        action_ids = ([amo.LOG.THEME_REVIEW.id] if theme
                      else constants.activity.LOG_REVIEWER_REVIEW_ACTION)
        return (qs.values('user', 'user__display_name', 'user__username')
                  .filter(action__in=action_ids)
                  .exclude(user__id=settings.TASK_USER_ID)
                  .annotate(approval_count=models.Count('id'))
                  .order_by('-approval_count'))

    def monthly_reviews(self, theme=False):
        """Return the top users for the month, and their # of reviews."""
        qs = self._by_type()
        now = datetime.now()
        created_date = datetime(now.year, now.month, 1)
        actions = ([constants.activity.LOG.THEME_REVIEW.id] if theme
                   else constants.activity.LOG_REVIEWER_REVIEW_ACTION)
        return (qs.values('user', 'user__display_name', 'user__username')
                  .filter(created__gte=created_date,
                          action__in=actions)
                  .exclude(user__id=settings.TASK_USER_ID)
                  .annotate(approval_count=models.Count('id'))
                  .order_by('-approval_count'))

    def user_approve_reviews(self, user):
        qs = self._by_type()
        return qs.filter(
            action__in=constants.activity.LOG_REVIEWER_REVIEW_ACTION,
            user__id=user.id)

    def current_month_user_approve_reviews(self, user):
        now = datetime.now()
        ago = datetime(now.year, now.month, 1)
        return self.user_approve_reviews(user).filter(created__gte=ago)

    def user_position(self, values_qs, user):
        try:
            return next(i for (i, d) in enumerate(list(values_qs))
                        if d.get('user') == user.id) + 1
        except StopIteration:
            return None

    def total_ratings_user_position(self, user, theme=False):
        return self.user_position(self.total_ratings(theme), user)

    def monthly_reviews_user_position(self, user, theme=False):
        return self.user_position(self.monthly_reviews(theme), user)

    def _by_type(self):
        qs = self.get_queryset()
        table = 'log_activity_addon'
        return qs.extra(
            tables=[table],
            where=['%s.activity_log_id=%s.id'
                   % (table, 'log_activity')])


class SafeFormatter(string.Formatter):
    """A replacement for str.format that escapes interpolated values."""

    def get_field(self, *args, **kw):
        # obj is the value getting interpolated into the string.
        obj, used_key = super(SafeFormatter, self).get_field(*args, **kw)
        return jinja2.escape(obj), used_key


class ActivityLog(ModelBase):
    TYPES = sorted(
        [(value.id, key)
         for key, value in constants.activity.LOG_BY_ID.items()])
    user = models.ForeignKey(
        'users.UserProfile', null=True, on_delete=models.SET_NULL)
    action = models.SmallIntegerField(choices=TYPES)
    _arguments = models.TextField(blank=True, db_column='arguments')
    _details = models.TextField(blank=True, db_column='details')
    objects = ActivityLogManager()

    formatter = SafeFormatter()

    class Meta:
        db_table = 'log_activity'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=('action',), name='log_activity_1bd4707b'),
            models.Index(fields=('created',), name='created_idx'),
        ]

    def f(self, *args, **kw):
        """Calls SafeFormatter.format and returns a Markup string."""
        # SafeFormatter escapes everything so this is safe.
        return jinja2.Markup(self.formatter.format(*args, **kw))

    @classmethod
    def arguments_builder(cls, activities):
        # We need to do 2 passes on each log:
        # - The first time, gather the references to every instance we need
        # - The second time, we built querysets for all instances of the same
        #   type, pick data from that queryset.
        #
        # Because it relies on in_bulk(), this method needs the pks to be of a
        # consistent type, which doesn't appear to be guaranteed in our
        # existing data. For this reason, it forces a conversion to int. If we
        # ever want to store ActivityLog items pointing to models using a non
        # integer PK field, we'll need to make this a little smarter.
        instances_to_load = defaultdict(list)
        instances = {}

        for activity in activities:
            try:
                # `arguments_data` will be a list of dicts like:
                # `[{'addons.addon':12}, {'addons.addon':1}, ... ]`
                activity.arguments_data = json.loads(activity._arguments)
            except Exception as e:
                log.info(
                    'unserializing data from activity_log failed: %s',
                    activity.id)
                log.info(e)
                activity.arguments_data = []

            for item in activity.arguments_data:
                # Each 'item' should have one key and one value only.
                name, pk = list(item.items())[0]
                if name not in ('str', 'int', 'null') and pk:
                    # Convert pk to int to have consistent data for when we
                    # call .in_bulk() later.
                    instances_to_load[name].append(int(pk))

        # At this point, instances_to_load is a dict of "names" that
        # each have a bunch of pks we want to load.
        for name, pks in instances_to_load.items():
            # Cope with renames of key models (use the original model name like
            # it was in the ActivityLog as the key so that we can find it
            # later)
            key = name
            if key == 'reviews.review':
                name = 'ratings.rating'
            (app_label, model_name) = name.split('.')
            model = apps.get_model(app_label, model_name)
            # Load the instances, avoiding transformers other than translations
            # and coping with soft-deleted models and unlisted add-ons.
            qs = model.get_unfiltered_manager().all()
            if hasattr(qs, 'only_translations'):
                qs = qs.only_translations()
            instances[key] = qs.in_bulk(pks)

        # instances is now a dict of "model names" that each have a dict of
        # {pk: instance}. We do our second pass on the logs to build the
        # "arguments" property from that data, which is a list of the instances
        # that each particular log has, in the correct order.
        for activity in activities:
            objs = []
            # We preloaded that property earlier
            for item in activity.arguments_data:
                # As above, each 'item' should have one key and one value only.
                name, pk = list(item.items())[0]
                if name in ('str', 'int', 'null'):
                    # It's not actually a model reference, just return the
                    # value directly.
                    objs.append(pk)
                elif pk:
                    # Fetch the instance from the cache we built.
                    objs.append(instances[name].get(int(pk)))
            # Override the arguments cached_property with what we got.
            activity.arguments = objs

    @cached_property
    def arguments(self):
        # This is a fallback : in 99% of the cases we should not be using this
        # but go through the default transformer instead, which executes
        # arguments_builder on the whole list of items in the queryset,
        # allowing us to fetch the instances in arguments in an optimized
        # manner.
        self.arguments_builder([self])
        return self.arguments

    def set_arguments(self, args=None):
        """
        Takes an object or a tuple of objects and serializes them and stores it
        in the db as a json string.
        """
        if args is None:
            args = []

        if not isinstance(args, (list, tuple)):
            args = (args,)

        serialize_me = []

        for arg in args:
            if isinstance(arg, str):
                serialize_me.append({'str': arg})
            elif isinstance(arg, int):
                serialize_me.append({'int': arg})
            elif isinstance(arg, tuple):
                # Instead of passing an addon instance you can pass a tuple:
                # (Addon, 3) for Addon with pk=3
                serialize_me.append(dict(((str(arg[0]._meta), arg[1]),)))
            else:
                serialize_me.append(dict(((str(arg._meta), arg.pk),)))

        self._arguments = json.dumps(serialize_me)

    @property
    def details(self):
        if self._details:
            return json.loads(self._details)

    @details.setter
    def details(self, data):
        self._details = json.dumps(data)

    @property
    def log(self):
        return constants.activity.LOG_BY_ID[self.action]

    def to_string(self, type_=None):
        log_type = constants.activity.LOG_BY_ID[self.action]
        if type_ and hasattr(log_type, '%s_format' % type_):
            format = getattr(log_type, '%s_format' % type_)
        else:
            format = log_type.format

        # We need to copy arguments so we can remove elements from it
        # while we loop over self.arguments.
        arguments = copy(self.arguments)
        addon = None
        rating = None
        version = None
        collection = None
        tag = None
        group = None
        file_ = None
        status = None

        for arg in self.arguments:
            if isinstance(arg, Addon) and not addon:
                if arg.has_listed_versions():
                    addon = self.f(u'<a href="{0}">{1}</a>',
                                   arg.get_url_path(), arg.name)
                else:
                    addon = self.f(u'{0}', arg.name)
                arguments.remove(arg)
            if isinstance(arg, Rating) and not rating:
                rating = self.f(u'<a href="{0}">{1}</a>',
                                arg.get_url_path(), ugettext('Review'))
                arguments.remove(arg)
            if isinstance(arg, Version) and not version:
                text = ugettext('Version {0}')
                if arg.channel == amo.RELEASE_CHANNEL_LISTED:
                    version = self.f(u'<a href="{1}">%s</a>' % text,
                                     arg.version, arg.get_url_path())
                else:
                    version = self.f(text, arg.version)
                arguments.remove(arg)
            if isinstance(arg, Collection) and not collection:
                collection = self.f(u'<a href="{0}">{1}</a>',
                                    arg.get_url_path(), arg.name)
                arguments.remove(arg)
            if isinstance(arg, Tag) and not tag:
                if arg.can_reverse():
                    tag = self.f(u'<a href="{0}">{1}</a>',
                                 arg.get_url_path(), arg.tag_text)
                else:
                    tag = self.f('{0}', arg.tag_text)
            if isinstance(arg, Group) and not group:
                group = arg.name
                arguments.remove(arg)
            if isinstance(arg, File) and not file_:
                validation = 'passed'
                if self.action in (
                        amo.LOG.UNLISTED_SIGNED.id,
                        amo.LOG.UNLISTED_SIGNED_VALIDATION_FAILED.id):
                    validation = 'ignored'

                file_ = self.f(u'<a href="{0}">{1}</a> (validation {2})',
                               arg.get_url_path(src=None),
                               arg.filename,
                               validation)
                arguments.remove(arg)
            if (self.action == amo.LOG.CHANGE_STATUS.id and
                    not isinstance(arg, Addon)):
                # Unfortunately, this action has been abused in the past and
                # the non-addon argument could be a string or an int. If it's
                # an int, we want to retrieve the string and translate it.
                if isinstance(arg, int) and arg in amo.STATUS_CHOICES_ADDON:
                    status = ugettext(amo.STATUS_CHOICES_ADDON[arg])
                else:
                    # It's not an int or not one of the choices, so assume it's
                    # a string or an unknown int we want to display as-is.
                    status = arg
                arguments.remove(arg)

        user = user_link(self.user)

        try:
            kw = {
                'addon': addon,
                'rating': rating,
                'version': version,
                'collection': collection,
                'tag': tag,
                'user': user,
                'group': group,
                'file': file_,
                'status': status,
            }
            return self.f(str(format), *arguments, **kw)
        except (AttributeError, KeyError, IndexError):
            log.warning('%d contains garbage data' % (self.id or 0))
            return 'Something magical happened.'

    def __str__(self):
        return self.to_string()

    def __html__(self):
        return self

    @property
    def author_name(self):
        """Name of the user that triggered the activity.

        If it's a reviewer action that will be shown to developers, the
        `reviewer_name` property is used if present, otherwise `name` is
        used."""
        if self.action in constants.activity.LOG_REVIEW_QUEUE_DEVELOPER:
            return self.user.reviewer_name or self.user.name
        return self.user.name

    @classmethod
    def create(cls, action, *args, **kw):
        """
        e.g. ActivityLog.create(amo.LOG.CREATE_ADDON, addon),
             ActivityLog.create(amo.LOG.ADD_FILE_TO_VERSION, file, version)
        In case of circular import you can use `olympia.activity.log_create()`
        """
        from olympia import core

        user = kw.get('user', core.get_user())

        if not user:
            log.warning('Activity log called with no user: %s' % action.id)
            return

        # We make sure that we take the timestamp if provided, instead of
        # creating a new one, especially useful for log entries created
        # in a loop.
        al = ActivityLog(
            user=user, action=action.id,
            created=kw.get('created', timezone.now()))
        al.set_arguments(args)
        if 'details' in kw:
            al.details = kw['details']
        al.save()

        if 'details' in kw and 'comments' in al.details:
            CommentLog.objects.create(
                comments=al.details['comments'], activity_log=al,
                created=kw.get('created', timezone.now()))

        for arg in args:
            if isinstance(arg, tuple):
                class_ = arg[0]
                id_ = arg[1]
            else:
                class_ = arg.__class__
                id_ = arg.id if isinstance(arg, ModelBase) else None

            if class_ == Addon:
                AddonLog.objects.create(
                    addon_id=id_, activity_log=al,
                    created=kw.get('created', timezone.now()))
            elif class_ == Version:
                VersionLog.objects.create(
                    version_id=id_, activity_log=al,
                    created=kw.get('created', timezone.now()))
            elif class_ == UserProfile:
                UserLog.objects.create(
                    user_id=id_, activity_log=al,
                    created=kw.get('created', timezone.now()))
            elif class_ == Group:
                GroupLog.objects.create(
                    group_id=id_, activity_log=al,
                    created=kw.get('created', timezone.now()))
            elif class_ == Block:
                BlockLog.objects.create(
                    block_id=id_, activity_log=al, guid=arg.guid,
                    created=kw.get('created', timezone.now()))

        # Index by every user
        UserLog.objects.create(
            activity_log=al, user=user,
            created=kw.get('created', timezone.now()))
        return al
