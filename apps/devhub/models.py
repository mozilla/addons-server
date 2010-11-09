from copy import copy
from datetime import datetime
import json

from django.db import models

import commonware.log
from tower import ugettext_lazy as _
from uuidfield.fields import UUIDField

import amo
import amo.models
from addons.models import Addon
from bandwagon.models import Collection
from reviews.models import Review
from translations.fields import TranslatedField
from users.models import UserProfile
from versions.models import Version

log = commonware.log.getLogger('devhub')


class RssKey(models.Model):
    key = UUIDField(db_column='rsskey', auto=True, unique=True)
    addon = models.ForeignKey(Addon, null=True, unique=True)
    user = models.ForeignKey(UserProfile, null=True, unique=True)
    created = models.DateField(default=datetime.now)

    class Meta:
        db_table = 'hubrsskeys'


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
        db_table = 'log_activity_addon'
        ordering = ('-created',)


class UserLog(amo.models.ModelBase):
    """
    This table is for indexing the activity log by user.
    Note: This includes activity performed unto the user.
    """
    activity_log = models.ForeignKey('ActivityLog')
    user = models.ForeignKey(UserProfile)

    class Meta:
        db_table = 'log_activity_user'
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

    def for_user(self, user):
        vals = (UserLog.objects.filter(user=user)
                    .values_list('activity_log', flat=True))
        return self.filter(pk__in=list(vals))


class ActivityLog(amo.models.ModelBase):
    TYPES = [(value, key) for key, value in amo.LOG.items()]
    user = models.ForeignKey('users.UserProfile', null=True)
    action = models.SmallIntegerField(choices=TYPES, db_index=True)
    _arguments = models.TextField(blank=True, db_column='arguments')
    objects = ActivityLogManager()

    @property
    def arguments(self):

        try:
            # d is a structure:
            # ``d = [{'addons.addon'=12}, {'addons.addon'=1}, ... ]``
            d = json.loads(self._arguments)
        except:
            log.debug('unserializing data from addon_log failed: %s' % self.id)
            return None

        objs = []
        for item in d:
            # item has only one element.
            model_name, pk = item.items()[0]
            if model_name == 'str':
                objs.append(pk)
            else:
                (app_label, model_name) = model_name.split('.')
                model = models.loading.get_model(app_label, model_name)
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
            elif isinstance(arg, tuple):
                # Instead of passing an addon instance you can pass a tuple:
                # (Addon, 3) for Addon with pk=3
                serialize_me.append(dict(((unicode(arg[0]._meta), arg[1]),)))
            else:
                serialize_me.append(dict(((unicode(arg._meta), arg.pk),)))

        self._arguments = json.dumps(serialize_me)

    # TODO(davedash): Support other types.
    def to_string(self, type='default'):
        log_type = amo.LOG_BY_ID[self.action]

        # We need to copy arguments so we can remove elements from it
        # while we loop over self.arguments.
        arguments = copy(self.arguments)
        addon = None
        review = None
        version = None
        collection = None
        for arg in self.arguments:
            if isinstance(arg, Addon) and not addon:
                addon = u'<a href="%s">%s</a>' % (arg.get_url_path(), arg.name)
                arguments.remove(arg)
            if isinstance(arg, Review) and not review:
                review = u'<a href="%s">%s</a>' % (arg.get_url_path(),
                                                   _('Review'))
                arguments.remove(arg)
            if isinstance(arg, Version) and not version:
                text = _('Version %s') % arg.version
                version = u'<a href="%s">%s</a>' % (arg.get_url_path(), text)
                arguments.remove(arg)
            if isinstance(arg, Collection) and not collection:
                collection = u'<a href="%s">%s</a>' % (arg.get_url_path(),
                                                       arg.name)
                arguments.remove(arg)

        try:
            data = dict(user=self.user, addon=addon, review=review,
                        version=version, collection=collection)
            return log_type.format.format(*arguments, **data)
        except (AttributeError, KeyError, IndexError):
            log.warning('%d contains garbage data' % (self.id or 0))
            return 'Something magical happened.'

    def __unicode__(self):
        return self.to_string()

    class Meta:
        db_table = 'log_activity'
        ordering = ('-created',)


# TODO(davedash): Remove after we finish the import.
class LegacyAddonLog(models.Model):
    TYPES = [(value, key) for key, value in amo.LOG.items()]

    addon = models.ForeignKey('addons.Addon', null=True, blank=True)
    user = models.ForeignKey('users.UserProfile', null=True)
    type = models.SmallIntegerField(choices=TYPES)
    object1_id = models.IntegerField(null=True, blank=True)
    object2_id = models.IntegerField(null=True, blank=True)
    name1 = models.CharField(max_length=255, default='', blank=True)
    name2 = models.CharField(max_length=255, default='', blank=True)
    notes = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'addonlogs'
