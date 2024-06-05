import json
import uuid
from collections import defaultdict
from copy import copy
from inspect import isclass

from django.apps import apps
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.html import format_html, mark_safe
from django.utils.translation import gettext, ngettext

import olympia.core.logger
from olympia import amo, constants
from olympia.abuse.models import CinderPolicy
from olympia.access.models import Group
from olympia.addons.models import Addon
from olympia.amo.fields import IPAddressBinaryField, PositiveAutoField
from olympia.amo.models import BaseQuerySet, LongNameIndex, ManagerBase, ModelBase
from olympia.bandwagon.models import Collection
from olympia.blocklist.models import Block
from olympia.constants.activity import _LOG
from olympia.files.models import File
from olympia.ratings.models import Rating
from olympia.reviewers.models import ReviewActionReason
from olympia.tags.models import Tag
from olympia.users.models import UserProfile
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.amo.activity')

# Number of times a token can be used.
MAX_TOKEN_USE_COUNT = 100

GENERIC_USER_NAME = gettext('Add-ons Review Team')


class GenericMozillaUser(UserProfile):
    class Meta:
        proxy = True

    @property
    def name(self):
        return GENERIC_USER_NAME


class ActivityLogToken(ModelBase):
    id = PositiveAutoField(primary_key=True)
    version = models.ForeignKey(Version, related_name='token', on_delete=models.CASCADE)
    user = models.ForeignKey(
        'users.UserProfile',
        related_name='activity_log_tokens',
        on_delete=models.CASCADE,
    )
    uuid = models.UUIDField(default=uuid.uuid4, unique=True)
    use_count = models.IntegerField(
        default=0, help_text='Stores the number of times the token has been used'
    )

    class Meta:
        db_table = 'log_activity_tokens'
        constraints = [
            models.UniqueConstraint(fields=('version', 'user'), name='version_id'),
        ]

    def is_expired(self):
        return self.use_count >= MAX_TOKEN_USE_COUNT

    def is_valid(self):
        return (
            not self.is_expired()
            and self.version
            == self.version.addon.find_latest_version(
                channel=self.version.channel, exclude=()
            )
        )

    def expire(self):
        self.update(use_count=MAX_TOKEN_USE_COUNT)

    def increment_use(self):
        self.__class__.objects.filter(pk=self.pk).update(
            use_count=models.expressions.F('use_count') + 1
        )
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
            log.info(
                'unserializing data from addon_log failed: %s' % self.activity_log.id
            )
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
    comments = models.TextField(max_length=100000)

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


class ReviewActionReasonLog(ModelBase):
    """
    This table allows ReviewActionReasons to be assigned to ActivityLog entries.
    """

    activity_log = models.ForeignKey('ActivityLog', on_delete=models.CASCADE)
    reason = models.ForeignKey(ReviewActionReason, on_delete=models.CASCADE)

    class Meta:
        db_table = 'log_activity_review_action_reason'
        ordering = ('-created',)


class CinderPolicyLog(ModelBase):
    """
    This table allows CinderPolicy instances to be assigned to ActivityLog entries.
    """

    activity_log = models.ForeignKey('ActivityLog', on_delete=models.CASCADE)
    cinder_policy = models.ForeignKey(CinderPolicy, on_delete=models.CASCADE)

    class Meta:
        db_table = 'log_activity_cinder_policy'
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


class IPLog(ModelBase):
    """
    This table is for indexing the activity log by IP (only for specific
    actions).
    """

    activity_log = models.OneToOneField('ActivityLog', on_delete=models.CASCADE)
    _ip_address = models.CharField(max_length=45, db_column='ip_address', null=True)
    ip_address_binary = IPAddressBinaryField(null=True)

    class Meta:
        db_table = 'log_activity_ip'
        ordering = ('-created',)
        indexes = [
            LongNameIndex(
                fields=('_ip_address',),
                name='log_activity_ip_ip_address_ba36172a',
            ),
            LongNameIndex(
                fields=('ip_address_binary',),
                name='log_activity_ip_ip_address_binary_209777a9',
            ),
        ]

    def __str__(self):
        return str(self.ip_address_binary)

    def save(self, *args, **kwargs):
        # ip_address_binary fulfils our needs, but we're keeping filling ip_address for
        # now, until any existing manual queries are updated.
        self._ip_address = str(self.ip_address_binary)
        return super().save(*args, **kwargs)


class RatingLog(ModelBase):
    """
    This table is for indexing the activity log by Ratings (user reviews).
    """

    id = PositiveAutoField(primary_key=True)
    activity_log = models.ForeignKey('ActivityLog', on_delete=models.CASCADE)
    rating = models.ForeignKey(Rating, on_delete=models.SET_NULL, null=True)

    class Meta:
        db_table = 'log_activity_rating'
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

    def for_block(self, block):
        return self.filter(blocklog__block=block)

    def for_guidblock(self, guid):
        return self.filter(blocklog__guid=guid)

    def moderation_events(self):
        return self.filter(action__in=constants.activity.LOG_RATING_MODERATION)

    def review_log(self):
        qs = (
            self.get_queryset()
            .filter(action__in=constants.activity.LOG_REVIEWER_REVIEW_ACTION)
            .exclude(user__id=settings.TASK_USER_ID)
        )
        return qs

    def create(self, *args, **kw):
        """
        e.g. ActivityLog.objects.create(amo.LOG.CREATE_ADDON, addon),
             ActivityLog.objects.create(amo.LOG.ADD_FILE_TO_VERSION, file, version)
        In case of circular import you can use `olympia.activity.log_create()`
        """
        from olympia import core

        # typical usage is action as first arg, but it could be a kwarg instead
        if 'action' in kw:
            action_arg = kw.pop('action')
        else:
            action_arg, *args = args

        # We might get action as an int, as that's what the model field is defined as
        action = (
            action_arg
            if isclass(action_arg) and issubclass(action_arg, _LOG)
            else amo.LOG_BY_ID[action_arg]
        )

        user = kw.get('user', core.get_user())

        if not user:
            log.warning('Activity log called with no user: %s' % action.id)
            return

        # We make sure that we take the timestamp if provided, instead of
        # creating a new one, especially useful for log entries created
        # in a loop.
        al = super().create(
            user=user, action=action.id, created=kw.get('created', timezone.now())
        )
        al.set_arguments(args)
        if 'details' in kw:
            al.details = kw['details']
        al.save()

        if 'details' in kw and 'comments' in al.details:
            CommentLog.objects.create(
                comments=al.details['comments'],
                activity_log=al,
                created=kw.get('created', timezone.now()),
            )

        bulk_objects = defaultdict(list)
        for arg in args:
            create_kwargs = {
                'activity_log': al,
                'created': kw.get('created', timezone.now()),
            }
            if isinstance(arg, tuple):
                class_ = arg[0]
                id_ = arg[1]
            else:
                class_ = arg.__class__
                id_ = arg.id if isinstance(arg, ModelBase) else None

            if class_ == Addon:
                bulk_objects[AddonLog].append(AddonLog(addon_id=id_, **create_kwargs))
            elif class_ == Version:
                bulk_objects[VersionLog].append(
                    VersionLog(version_id=id_, **create_kwargs)
                )
            elif class_ == Group:
                bulk_objects[GroupLog].append(GroupLog(group_id=id_, **create_kwargs))
            elif class_ == Block:
                bulk_objects[BlockLog].append(
                    BlockLog(block_id=id_, guid=arg.guid, **create_kwargs)
                )
            elif class_ == ReviewActionReason:
                bulk_objects[ReviewActionReasonLog].append(
                    ReviewActionReasonLog(reason_id=id_, **create_kwargs)
                )
            elif class_ == CinderPolicy:
                bulk_objects[CinderPolicyLog].append(
                    CinderPolicyLog(cinder_policy_id=id_, **create_kwargs)
                )
            elif class_ == Rating:
                bulk_objects[RatingLog].append(
                    RatingLog(rating_id=id_, **create_kwargs)
                )
        for klass, instances in bulk_objects.items():
            klass.objects.bulk_create(instances)

        if getattr(action, 'store_ip', False) and (
            ip_address := core.get_remote_addr()
        ):
            # Index specific actions by their IP address. Note that the caller
            # must take care of overriding remote addr if the action is created
            # from a task.
            IPLog.objects.create(
                ip_address_binary=ip_address,
                activity_log=al,
                created=kw.get('created', timezone.now()),
            )

        return al


class ActivityLog(ModelBase):
    TYPES = sorted(
        (value.id, key) for key, value in constants.activity.LOG_BY_ID.items()
    )
    # We should never hard-delete users, so the on_delete can be set to DO_NOTHING,
    # if somehow a hard-delete still occurs, it will raise an IntegrityError.
    user = models.ForeignKey('users.UserProfile', on_delete=models.DO_NOTHING)
    action = models.SmallIntegerField(choices=TYPES)
    _arguments = models.TextField(blank=True, db_column='arguments')
    _details = models.TextField(blank=True, db_column='details')
    objects = ActivityLogManager()

    class Meta:
        db_table = 'log_activity'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=('action',), name='log_activity_1bd4707b'),
            models.Index(fields=('created',), name='log_activity_created_idx'),
        ]

    @classmethod
    def transformer_anonymize_user_for_developer(cls, logs):
        """Replace the user with a generic user in actions where it shouldn't
        be shown to a developer.
        """
        generic_user = GenericMozillaUser()

        for log in logs:
            if log.action not in constants.activity.LOG_SHOW_USER_TO_DEVELOPER:
                log.user = generic_user

    @classmethod
    def arguments_builder(cls, activities):
        def handle_renames(value):
            # Cope with renames of key models (use the original model name like
            # it was in the ActivityLog as the key so that we can find it
            # later)
            return 'ratings.rating' if value == 'reviews.review' else value

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
                log.info('unserializing data from activity_log failed: %s', activity.id)
                log.info(e)
                activity.arguments_data = []

            for item in activity.arguments_data:
                # Each 'item' should have one key and one value only.
                name, pk = list(item.items())[0]
                if name not in ('str', 'int', 'null') and pk:
                    # Convert pk to int to have consistent data for when we
                    # call .in_bulk() later.
                    name = handle_renames(name)
                    instances_to_load[name].append(int(pk))

        # At this point, instances_to_load is a dict of "names" that
        # each have a bunch of pks we want to load.
        for name, pks in instances_to_load.items():
            (app_label, model_name) = name.split('.')
            model = apps.get_model(app_label, model_name)
            # Load the instances, avoiding transformers other than translations
            # and coping with soft-deleted models and unlisted add-ons.
            qs = model.get_unfiltered_manager().all()
            if hasattr(qs, 'only_translations'):
                qs = qs.only_translations()
            instances[name] = qs.in_bulk(pks)

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
                    name = handle_renames(name)
                    obj = instances[name].get(int(pk))
                    # Most of the time, we're eventually going to call
                    # to_string() on each ActivityLog that we're processing
                    # here. For some of the models, that will result in a call
                    # to <model>.get_absolute_url(), which in turn can cause an
                    # extra SQL query because some parent model is needed to
                    # build the URL.
                    # It's difficult to predict what we'll need as ActivitLog
                    # is fairly generic, but we know Addon is going to be
                    # needed in some cases for sure (Version, Rating) so if
                    # we're dealing with objects that have an `addon_id`
                    # property, and we have already fetched the corresponding
                    # Addon instance, set the `addon`  property on the object
                    # to the Addon instance we already have to avoid the extra
                    # SQL query.
                    addon_id = getattr(obj, 'addon_id', None)
                    if addon := instances.get('addons.addon', {}).get(addon_id):
                        obj.addon = addon
                    objs.append(obj)
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
        absolute_url_method = (
            'get_admin_absolute_url' if type_ == 'admin' else 'get_absolute_url'
        )

        def get_absolute_url(obj):
            return getattr(obj, absolute_url_method)() if obj is not None else ''

        # We need to copy arguments so we can remove elements from it
        # while we loop over self.arguments.
        arguments = copy(self.arguments)
        addon = None
        addon_name = None
        addon_pk = None
        rating = None
        version = None
        collection = None
        tag = None
        group = None
        file_ = None
        status = None
        user = None
        channel = None
        _versions = []

        for arg in self.arguments:
            if isinstance(arg, Addon) and not addon:
                addon_pk = arg.pk
                addon_name = arg.name
                # _current_version_id as an approximation to see if the add-on
                # has listed versions without doing extra queries.
                if type_ == 'admin' or arg._current_version_id:
                    addon = format_html(
                        '<a href="{0}">{1}</a>', get_absolute_url(arg), addon_name
                    )
                else:
                    addon = format_html('{0}', arg.name)
                arguments.remove(arg)
            if isinstance(arg, Rating) and not rating:
                rating = format_html(
                    '<a href="{0}">{1}</a>', get_absolute_url(arg), gettext('Review')
                )
                arguments.remove(arg)
            if isinstance(arg, Version):
                # Versions can appear multiple time. Append to an intermediary
                # _versions list, and use that later to build the final
                # 'version' argument used for formatting.
                channel = arg.channel
                if type_ == 'admin' or (
                    type_ != 'reviewlog' and arg.channel == amo.CHANNEL_LISTED
                ):
                    _versions.append(
                        format_html(
                            '<a href="{0}">{1}</a>',
                            get_absolute_url(arg),
                            arg.version,
                        )
                    )
                else:
                    _versions.append(arg.version)
                arguments.remove(arg)
            if isinstance(arg, Collection) and not collection:
                collection = format_html(
                    '<a href="{0}">{1}</a>', get_absolute_url(arg), arg.name
                )
                arguments.remove(arg)
            if isinstance(arg, Tag) and not tag:
                if arg.can_reverse():
                    tag = format_html(
                        '<a href="{0}">{1}</a>', get_absolute_url(arg), arg.tag_text
                    )
                else:
                    tag = format_html('{0}', arg.tag_text)
            if isinstance(arg, Group) and not group:
                group = arg.name
                arguments.remove(arg)
            if isinstance(arg, File) and not file_:
                validation = 'passed'
                if self.action in (
                    amo.LOG.UNLISTED_SIGNED.id,
                    amo.LOG.UNLISTED_SIGNED_VALIDATION_FAILED.id,
                ):
                    validation = 'ignored'

                file_ = format_html(
                    '<a href="{0}">{1}</a> (validation {2})',
                    get_absolute_url(arg),
                    arg.pretty_filename,
                    validation,
                )
                arguments.remove(arg)
            if isinstance(arg, UserProfile) and not user:
                user = format_html(
                    '<a href="{0}">{1}</a>', get_absolute_url(arg), arg.name
                )
                arguments.remove(arg)
            if self.action == amo.LOG.CHANGE_STATUS.id and not isinstance(arg, Addon):
                # Unfortunately, this action has been abused in the past and
                # the non-addon argument could be a string or an int. If it's
                # an int, we want to retrieve the string and translate it.
                if isinstance(arg, int) and arg in amo.STATUS_CHOICES_ADDON:
                    status = gettext(amo.STATUS_CHOICES_ADDON[arg])
                else:
                    # It's not an int or not one of the choices, so assume it's
                    # a string or an unknown int we want to display as-is.
                    status = arg
                arguments.remove(arg)

        user_responsible = format_html(
            '<a href="{0}">{1}</a>', get_absolute_url(self.user), self.user.name
        )

        if _versions:
            # Now that all arguments have been processed we can build a string
            # for all the versions and build a string for addon that is
            # specific to the reviewlog, with the correct channel for the
            # review page link.
            version = format_html(
                ngettext('Version {0}', 'Versions {0}', len(_versions)),
                # We're only joining already escaped/safe content.
                mark_safe(', '.join(_versions)),
            )

        if channel is None and self.details and 'channel' in self.details:
            channel = self.details['channel']

        if type_ == 'reviewlog' and addon and addon_pk and addon_name:
            reverse_args = [addon_pk]
            if self.action in (amo.LOG.REJECT_CONTENT.id, amo.LOG.APPROVE_CONTENT.id):
                reverse_args.insert(0, 'content')
            elif channel and channel == amo.CHANNEL_UNLISTED:
                reverse_args.insert(0, 'unlisted')
            addon = format_html(
                '<a href="{0}">{1}</a>',
                reverse('reviewers.review', args=reverse_args),
                addon_name,
            )

        try:
            kw = {
                'addon': addon,
                'rating': rating,
                'version': version,
                'collection': collection,
                'tag': tag,
                'user': user,
                'user_responsible': user_responsible,
                'group': group,
                'file': file_,
                'status': status,
            }
            return format_html(str(format), *arguments, **kw)
        except (AttributeError, KeyError, IndexError):
            log.warning('%d contains garbage data' % (self.id or 0))
            return 'Something magical happened.'

    def __str__(self):
        return self.to_string()

    def __html__(self):
        return self
