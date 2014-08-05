from collections import defaultdict
import json
import re

from jingo import register

import amo
from amo.urlresolvers import resolve, reverse
from bandwagon.models import (Collection, CollectionAddon, CollectionUser,
                              CollectionVote, CollectionWatcher)
from addons.models import Addon, AddonUser
from abuse.models import AbuseReport
from files.models import File, FileUpload
from reviews.models import Review
from users.models import UserProfile
from versions.models import Version

@register.function
def admin_site_links():
    return {
        'addons': [
            ('Search for add-ons by name or id', reverse('zadmin.addon-search')),
            ('Featured add-ons', reverse('zadmin.features')),
            ('Discovery Pane promo modules', reverse('discovery.module_admin')),
            ('Monthly Pick', reverse('zadmin.monthly_pick')),
            ('Upgrade jetpack add-ons', reverse('zadmin.jetpack')),
            ('Bulk add-on validation', reverse('zadmin.validation')),
            ('Fake mail', reverse('zadmin.mail')),
            ('Flagged reviews', reverse('zadmin.flagged')),
            ('ACR Reports', reverse('zadmin.compat')),
            ('Email Add-on Developers', reverse('zadmin.email_devs')),
        ],
        'users': [
            ('Configure groups', reverse('admin:access_group_changelist')),
        ],
        'settings': [
            ('View site settings', reverse('zadmin.settings')),
            ('Django admin pages', reverse('zadmin.home')),
            ('Site Events', reverse('zadmin.site_events')),
        ],
        'tools': [
            ('View request environment', reverse('amo.env')),
            ('Manage elasticsearch', reverse('zadmin.elastic')),
            ('Purge data from memcache', reverse('zadmin.memcache')),
            ('Purge pages from zeus', reverse('zadmin.hera')),
            ('Create a new OAuth Consumer',
             reverse('zadmin.oauth-consumer-create')),
            ('View event log', reverse('admin:editors_eventlog_changelist')),
            ('View addon log', reverse('admin:devhub_activitylog_changelist')),
            ('Generate error', reverse('zadmin.generate-error')),
            ('Site Status', reverse('amo.monitor')),
        ],
    }


class MassDeleteHelper(object):
    VIEW_MAP = {
        'addons.':             ('addon_id', Addon, 'slug'),
        'editors.review':      ('addon_id', Addon, 'slug'),
        'zadmin.addon_manage': ('addon_id', Addon, 'slug'),

        'addons.reviews.': ('review_id', Review, 'pk'),

        'users.':           ('user_id', UserProfile, 'username'),
        'users.admin_edit': ('user_id', UserProfile, 'pk'),

        'collections.': (('username', 'slug'),
                         Collection,
                         ('author__username', 'slug')),
    }

    MODEL_MAP = {
        'Addon': Addon,
        'Collection': Collection,
        'Review': Review,
        'UserProfile': UserProfile,
    }

    DELETION_MAP = {
        Addon: {
            'RELATED_MODELS': (
                (AbuseReport, 'addon_id'),
                (AddonUser, 'addon_id'),
                (CollectionAddon, 'addon_id'),
                (Review, 'addon_id'),
                (File, 'version__addon_id'),
                (Version, 'addon_id'),
            )
        },

        UserProfile: {
            'RELATED_MODELS': (
                (CollectionWatcher, 'collection__author_id'),
                (CollectionVote, 'collection__author_id'),
                (CollectionVote, 'user_id'),
                (CollectionUser, 'user_id'),
                (Collection, 'author_id'),
                (FileUpload, 'user_id'),
                (AbuseReport, 'reporter_id'),

                (AddonUser, 'user_id'),
                # Argh. Sometimes I hate Django's ORM.
                # I want `.exclude(authors__id__not_in=ids)`, but even with
                # `~Q(...)`, the NOT winds up outside of the generated
                # subselect rather than in it.
                (Addon, lambda objects, ids: (
                    objects.filter(authors__id__in=ids)
                           .extra(
                               where=['''
                                  `addons`.`id` NOT IN
                                      (SELECT `a2`.`id`
                                       FROM `addons` AS `a2`
                                       INNER JOIN `addons_users` AS `au2`
                                       ON `au2`.`addon_id` = `a2`.`id`
                                       WHERE `au2`.`user_id` NOT IN %s)
                               '''],
                               params=[ids]))),
            ),
        }
    }

    URL_LOP_RE  = re.compile(r'^https?://.*?/')
    VIEW_LOP_RE = re.compile(r'[^.]+\.?$')

    def __init__(self, objects=None, urls=None, reason=None):
        self.reason = reason

        if objects:
            self.object_types = objects

        if urls:
            self.objects = map(self.url_to_object, urls)
            self.unknown_urls = tuple(l
                                      for i, l in enumerate(urls)
                                      if not self.objects[i])

            object_types = defaultdict(list)
            for o in self.objects:
                if o:
                    object_types[o.__class__.__name__].append(o)

            self.object_types = dict(object_types.iteritems())

    @property
    def object_types_json(self):
        return json.dumps(self.object_types,
                          default=lambda o: o.pk)


    def url_to_object(self, url):
        to_tuple = lambda v: v if isinstance(v, tuple) else (v,)

        # Crudely lop off host and protocol part.
        url = self.URL_LOP_RE.sub('/', url)

        try:
            r = resolve(url)
        except:
            return None

        key = None
        view_id = r.url_name
        while not key and view_id:
            key = self.VIEW_MAP.get(view_id)
            args = key and map(r.kwargs.get, to_tuple(key[0]))

            if not (key and all(args)):
                key = None
                view_id = self.VIEW_LOP_RE.sub('', view_id)

        _, model, fields = key
        try:
            return model.objects.get(**dict(zip(to_tuple(fields),
                                                args)))
        except (ValueError, model.DoesNotExist):
            return None

    def delete_objects(self):
        for model_name, objs in self.object_types.iteritems():
            model = self.MODEL_MAP[model_name]
            ids = [o.pk for o in objs]

            amo.log(amo.LOG.ADMIN_MASS_DELETE, model_name,
                    json.dumps(map(unicode, objs)),
                    self.reason)

            for model_, qs in self.get_related_objects(model, ids):
                qs.delete()

            qs = model.objects.filter(pk__in=ids)
            qs.delete()

    def count_related(self, obj):
        model = obj.__class__
        counts = defaultdict(lambda: 0)

        for model, qs in self.get_related_objects(model, (obj.pk,)):
            count = qs.count()
            if count:
                counts[model.__name__] += count

        return sorted(counts.items())

    def get_related_objects(self, model, ids, seen=()):
        if model not in self.DELETION_MAP:
            return

        seen = set(seen)
        for key in self.DELETION_MAP[model]['RELATED_MODELS']:
            model, field = key

            qs = self.get_objects(model, field, ids)
            if model in self.DELETION_MAP and key not in seen:
                seen.add(key)

                pks = qs.values_list('pk', flat=True)
                for model_, qs_ in self.get_related_objects(model, pks,
                                                            seen=seen):
                    yield model_, qs_

            yield model, qs

    def get_objects(self, model, field, ids):
        if callable(field):
            return field(model.objects, ids)
        else:
            return model.objects.filter(**{'%s__in' % field: ids})

