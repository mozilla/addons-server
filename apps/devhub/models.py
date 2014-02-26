from copy import copy
from datetime import datetime
import imghdr
import json
import os.path
import string

from django.conf import settings
from django.core.urlresolvers import reverse
from django.db import models
from django.utils.safestring import mark_safe

import bleach
import commonware.log
import jinja2
from tower import ugettext as _
from uuidfield.fields import UUIDField

import amo
import amo.models
from access.models import Group
from addons.models import Addon
from bandwagon.models import Collection
from mkt.webapps.models import Webapp
from reviews.models import Review
from tags.models import Tag
from translations.fields import save_signal, TranslatedField
from users.helpers import user_link
from users.models import UserProfile
from versions.models import Version

log = commonware.log.getLogger('devhub')


table_name = lambda n: n + settings.LOG_TABLE_SUFFIX


class RssKey(models.Model):
    key = UUIDField(db_column='rsskey', auto=True, unique=True)
    addon = models.ForeignKey(Addon, null=True, unique=True)
    user = models.ForeignKey(UserProfile, null=True, unique=True)
    created = models.DateField(default=datetime.now)

    class Meta:
        db_table = 'hubrsskeys'


class BlogPost(amo.models.ModelBase):
    title = models.CharField(max_length=255)
    date_posted = models.DateField(default=datetime.now)
    permalink = models.CharField(max_length=255)

    class Meta:
        db_table = 'blogposts'


class HubPromo(amo.models.ModelBase):
    VISIBILITY_CHOICES = (
        (0, 'Nobody'),
        (1, 'Visitors'),
        (2, 'Developers'),
        (3, 'Visitors and Developers'),
    )

    heading = TranslatedField()
    body = TranslatedField()
    visibility = models.SmallIntegerField(choices=VISIBILITY_CHOICES)

    class Meta:
        db_table = 'hubpromos'

    def __unicode__(self):
        return unicode(self.heading)

    def flush_urls(self):
        return ['*/developers*']

models.signals.pre_save.connect(save_signal, sender=HubPromo,
                                dispatch_uid='hubpromo_translations')


class HubEvent(amo.models.ModelBase):
    name = models.CharField(max_length=255, default='')
    url = models.URLField(max_length=255, default='')
    location = models.CharField(max_length=255, default='')
    date = models.DateField(default=datetime.now)

    class Meta:
        db_table = 'hubevents'

    def __unicode__(self):
        return self.name

    def flush_urls(self):
        return ['*/developers*']


class AddonLog(amo.models.ModelBase):
    """
    This table is for indexing the activity log by addon.
    """
    addon = models.ForeignKey(Addon)
    activity_log = models.ForeignKey('ActivityLog')

    class Meta:
        # This table is addons only and not in use by the marketplace (except
        # for Themes).
        db_table = table_name('log_activity_addon')
        ordering = ('-created',)


class AppLog(amo.models.ModelBase):
    """
    This table is for indexing the activity log by app.
    """
    addon = models.ForeignKey(Webapp, db_constraint=False)
    activity_log = models.ForeignKey('ActivityLog')

    class Meta:
        db_table = table_name('log_activity_app')
        ordering = ('-created',)


class CommentLog(amo.models.ModelBase):
    """
    This table is for indexing the activity log by comment.
    """
    activity_log = models.ForeignKey('ActivityLog')
    comments = models.CharField(max_length=255)

    class Meta:
        db_table = table_name('log_activity_comment')
        ordering = ('-created',)


class VersionLog(amo.models.ModelBase):
    """
    This table is for indexing the activity log by version.
    """
    activity_log = models.ForeignKey('ActivityLog')
    version = models.ForeignKey(Version)

    class Meta:
        db_table = table_name('log_activity_version')
        ordering = ('-created',)


class UserLog(amo.models.ModelBase):
    """
    This table is for indexing the activity log by user.
    Note: This includes activity performed unto the user.
    """
    activity_log = models.ForeignKey('ActivityLog')
    user = models.ForeignKey(UserProfile)

    class Meta:
        db_table = table_name('log_activity_user')
        ordering = ('-created',)


class GroupLog(amo.models.ModelBase):
    """
    This table is for indexing the activity log by access group.
    """
    activity_log = models.ForeignKey('ActivityLog')
    group = models.ForeignKey(Group)

    class Meta:
        db_table = table_name('log_activity_group')
        ordering = ('-created',)


class ActivityLogManager(amo.models.ManagerBase):
    def for_addons(self, addons):
        if isinstance(addons, Addon):
            addons = (addons,)

        vals = (AddonLog.objects.filter(addon__in=addons)
                .values_list('activity_log', flat=True))

        if vals:
            return self.filter(pk__in=list(vals))
        else:
            return self.none()

    def for_apps(self, apps):
        if isinstance(apps, Webapp):
            apps = (apps,)

        vals = (AppLog.objects.filter(addon__in=apps)
                .values_list('activity_log', flat=True))

        if vals:
            return self.filter(pk__in=list(vals))
        else:
            return self.none()

    def for_version(self, version):
        vals = (VersionLog.objects.filter(version=version)
                .values_list('activity_log', flat=True))
        return self.filter(pk__in=list(vals))

    def for_group(self, group):
        return self.filter(grouplog__group=group)

    def for_user(self, user):
        vals = (UserLog.objects.filter(user=user)
                    .values_list('activity_log', flat=True))
        return self.filter(pk__in=list(vals))

    def for_developer(self):
        return self.exclude(action__in=amo.LOG_ADMINS + amo.LOG_HIDE_DEVELOPER)

    def admin_events(self):
        return self.filter(action__in=amo.LOG_ADMINS)

    def editor_events(self):
        return self.filter(action__in=amo.LOG_EDITORS)

    def review_queue(self, webapp=False):
        qs = self._by_type(webapp)
        return (qs.filter(action__in=amo.LOG_REVIEW_QUEUE)
                  .exclude(user__id=settings.TASK_USER_ID))

    def total_reviews(self, webapp=False, theme=False):
        qs = self._by_type(webapp)
        """Return the top users, and their # of reviews."""
        return (qs.values('user', 'user__display_name', 'user__username')
                  .filter(action__in=([amo.LOG.THEME_REVIEW.id] if theme
                                      else amo.LOG_REVIEW_QUEUE))
                  .exclude(user__id=settings.TASK_USER_ID)
                  .annotate(approval_count=models.Count('id'))
                  .order_by('-approval_count'))

    def monthly_reviews(self, webapp=False, theme=False):
        """Return the top users for the month, and their # of reviews."""
        qs = self._by_type(webapp)
        now = datetime.now()
        created_date = datetime(now.year, now.month, 1)
        return (qs.values('user', 'user__display_name', 'user__username')
                  .filter(created__gte=created_date,
                          action__in=([amo.LOG.THEME_REVIEW.id] if theme
                                      else amo.LOG_REVIEW_QUEUE))
                  .exclude(user__id=settings.TASK_USER_ID)
                  .annotate(approval_count=models.Count('id'))
                  .order_by('-approval_count'))

    def user_position(self, values_qs, user):
        try:
            return next(i for (i, d) in enumerate(list(values_qs))
                        if d.get('user') == user.id) + 1
        except StopIteration:
            return None

    def total_reviews_user_position(self, user, webapp=False, theme=False):
        return self.user_position(self.total_reviews(webapp, theme), user)

    def monthly_reviews_user_position(self, user, webapp=False, theme=False):
        return self.user_position(self.monthly_reviews(webapp, theme), user)

    def _by_type(self, webapp=False):
        qs = super(ActivityLogManager, self).get_query_set()
        table = (table_name('log_activity_app') if webapp
                 else table_name('log_activity_addon'))
        return qs.extra(
            tables=[table],
            where=['%s.activity_log_id=%s.id'
                   % (table, table_name('log_activity'))])


class SafeFormatter(string.Formatter):
    """A replacement for str.format that escapes interpolated values."""

    def get_field(self, *args, **kw):
        # obj is the value getting interpolated into the string.
        obj, used_key = super(SafeFormatter, self).get_field(*args, **kw)
        return jinja2.escape(obj), used_key


class ActivityLog(amo.models.ModelBase):
    TYPES = sorted([(value.id, key) for key, value in amo.LOG.items()])
    user = models.ForeignKey('users.UserProfile', null=True)
    action = models.SmallIntegerField(choices=TYPES, db_index=True)
    _arguments = models.TextField(blank=True, db_column='arguments')
    _details = models.TextField(blank=True, db_column='details')
    objects = ActivityLogManager()

    formatter = SafeFormatter()

    class Meta:
        db_table = table_name('log_activity')
        ordering = ('-created',)

    def f(self, *args, **kw):
        """Calls SafeFormatter.format and returns a Markup string."""
        # SafeFormatter escapes everything so this is safe.
        return jinja2.Markup(self.formatter.format(*args, **kw))

    @property
    def arguments(self):

        try:
            # d is a structure:
            # ``d = [{'addons.addon':12}, {'addons.addon':1}, ... ]``
            d = json.loads(self._arguments)
        except:
            log.debug('unserializing data from addon_log failed: %s' % self.id)
            return None

        objs = []
        for item in d:
            # item has only one element.
            model_name, pk = item.items()[0]
            if model_name in ('str', 'int', 'null'):
                objs.append(pk)
            else:
                (app_label, model_name) = model_name.split('.')
                model = models.loading.get_model(app_label, model_name)
                # Cope with soft deleted models.
                if hasattr(model, 'with_deleted'):
                    objs.extend(model.with_deleted.filter(pk=pk))
                else:
                    objs.extend(model.objects.filter(pk=pk))

        return objs

    @arguments.setter
    def arguments(self, args=[]):
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
            if isinstance(arg, basestring):
                serialize_me.append({'str': arg})
            elif isinstance(arg, (int, long)):
                serialize_me.append({'int': arg})
            elif isinstance(arg, tuple):
                # Instead of passing an addon instance you can pass a tuple:
                # (Addon, 3) for Addon with pk=3
                serialize_me.append(dict(((unicode(arg[0]._meta), arg[1]),)))
            else:
                serialize_me.append(dict(((unicode(arg._meta), arg.pk),)))

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
        return amo.LOG_BY_ID[self.action]

    def to_string(self, type_=None):
        log_type = amo.LOG_BY_ID[self.action]
        if type_ and hasattr(log_type, '%s_format' % type_):
            format = getattr(log_type, '%s_format' % type_)
        else:
            format = log_type.format

        # We need to copy arguments so we can remove elements from it
        # while we loop over self.arguments.
        arguments = copy(self.arguments)
        addon = None
        review = None
        version = None
        collection = None
        tag = None
        group = None

        for arg in self.arguments:
            if isinstance(arg, Addon) and not addon:
                addon = self.f(u'<a href="{0}">{1}</a>',
                               arg.get_url_path(), arg.name)
                arguments.remove(arg)
            if isinstance(arg, Review) and not review:
                review = self.f(u'<a href="{0}">{1}</a>',
                                arg.get_url_path(), _('Review'))
                arguments.remove(arg)
            if isinstance(arg, Version) and not version:
                text = _('Version {0}')
                if settings.MARKETPLACE:
                    version = self.f(text, arg.version)
                else:
                    version = self.f(u'<a href="{1}">%s</a>' % text,
                                     arg.version, arg.get_url_path())
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

        user = user_link(self.user)

        try:
            kw = dict(addon=addon, review=review, version=version,
                      collection=collection, tag=tag, user=user, group=group)
            return self.f(format, *arguments, **kw)
        except (AttributeError, KeyError, IndexError):
            log.warning('%d contains garbage data' % (self.id or 0))
            return 'Something magical happened.'

    def __unicode__(self):
        return self.to_string()

    def __html__(self):
        return self


# TODO: remove once we migrate to CommAtttachment (ngoke).
class ActivityLogAttachment(amo.models.ModelBase):
    """
    Model for an attachment to an ActivityLog instance. Used by the Marketplace
    reviewer tools, where reviewers can attach files to comments made during the
    review process.
    """
    activity_log = models.ForeignKey('ActivityLog')
    filepath = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    mimetype = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'log_activity_attachment_mkt'
        ordering = ('id',)

    def get_absolute_url(self):
        if settings.MARKETPLACE:
            return reverse('reviewers.apps.review.attachment', args=[self.pk])
        return None

    def filename(self):
        """
        Returns the attachment's file name.
        """
        return os.path.basename(self.filepath)

    def full_path(self):
        """
        Returns the full filesystem path of the attachment.
        """
        return os.path.join(settings.REVIEWER_ATTACHMENTS_PATH, self.filepath)

    def display_name(self):
        """
        Returns a string describing the attachment suitable for front-end
        display.
        """
        display = self.description if self.description else self.filename()
        return mark_safe(bleach.clean(display))

    def is_image(self):
        """
        Returns a boolean indicating whether the attached file is an image of a
        format recognizable by the stdlib imghdr module.
        """
        return imghdr.what(self.full_path()) is not None


class SubmitStep(models.Model):
    addon = models.ForeignKey(Addon)
    step = models.IntegerField()

    class Meta:
        db_table = 'submit_step'
