from datetime import datetime
import json

from django.db import models

import commonware.log

import amo
import amo.models
from addons.models import Addon
from users.models import UserProfile
from translations.fields import TranslatedField


log = commonware.log.getLogger('devhub')


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
    def for_addon(self, addon, limit=20, offset=0):
        vals = (AddonLog.objects.filter(addon=addon)[offset:limit]
                .values_list('activity_log', flat=True))
        return self.filter(pk__in=list(vals))

    def for_user(self, user, limit=20, offset=0):
        vals = (UserLog.objects.filter(user=user)[offset:limit]
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
            if isinstance(arg, str):
                serialize_me.append({'str': arg})
            else:
                serialize_me.append(dict(((unicode(arg._meta), arg.pk),)))

        self._arguments = json.dumps(serialize_me)

    @classmethod
    def log(cls, request, action, arguments=None):
        """
        e.g. ActivityLog.log(request, amo.LOG.CREATE_ADDON, []),
             ActivityLog.log(request, amo.LOG.ADD_FILE_TO_VERSION,
                             (file, version))
        """
        al = cls(user=request.amo_user, action=action.id)
        al.arguments = arguments
        al.save()

        if not isinstance(arguments, (list, tuple)):
            arguments = (arguments,)
        for arg in arguments:
            if isinstance(arg, Addon):
                AddonLog(addon=arg, activity_log=al).save()
            elif isinstance(arg, UserProfile):
                # Index by any user who is mentioned as an argument.
                UserLog(activity_log=al, user=arg).save()

        # Index by every request user
        UserLog(activity_log=al, user=request.amo_user).save()

    # TODO(davedash): Support other types.
    def to_string(self, type='default'):
        log_type = amo.LOG_BY_ID[self.action]
        arguments = self.arguments
        addon = None
        for arg in arguments:
            if isinstance(arg, Addon) and not addon:
                addon = arg
                break
        return log_type.format.format(*arguments, user=self.user, addon=addon)

    def __unicode__(self):
        return self.to_string()

    class Meta:
        db_table = 'log_activity'


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
