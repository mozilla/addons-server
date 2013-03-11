import hashlib
import logging
import random

from django.db.models import Q
from django.utils.encoding import smart_str

import commonware.log

import amo
from amo.utils import memoize

safe_key = lambda x: hashlib.md5(smart_str(x).lower().strip()).hexdigest()

log = commonware.log.getLogger('z.redis')
rnlog = logging.getLogger('z.rn')


def reverse_name_lookup(key, webapp=False):
    from addons.models import Addon
    addon_type = 'app' if webapp else 'addon'
    qs = Addon.objects.filter(name__localized_string=key).no_cache()
    if webapp:
        qs = qs.filter(type=amo.ADDON_WEBAPP)
    else:
        qs = qs.exclude(type=amo.ADDON_WEBAPP)
    values = list(qs.distinct().values_list('id', flat=True))
    if values:
        if len(values) > 1:
            rnlog.warning('Multiple returned for [%s:%s]: %s' % (addon_type,
                                                                 key, values))
        return values[0]
    return None  # Explicitly return None for no results


@memoize('addons:featured', time=60 * 10)
def get_featured_ids(app, lang=None, type=None):
    from addons.models import Addon
    ids = []
    is_featured = (Q(collections__featuredcollection__isnull=False) &
                   Q(collections__featuredcollection__application__id=app.id))
    qs = Addon.objects.all()

    if type:
        qs = qs.filter(type=type)
    if lang:
        has_locale = qs.filter(
            is_featured &
            Q(collections__featuredcollection__locale__iexact=lang))
        if has_locale.exists():
            ids += list(has_locale.distinct().values_list('id', flat=True))
        none_qs = qs.filter(
            is_featured &
            Q(collections__featuredcollection__locale__isnull=True))
        blank_qs = qs.filter(is_featured &
                             Q(collections__featuredcollection__locale=''))
        qs = none_qs | blank_qs
    else:
        qs = qs.filter(is_featured)
    other_ids = list(qs.distinct().values_list('id', flat=True))
    random.shuffle(ids)
    random.shuffle(other_ids)
    ids += other_ids
    return map(int, ids)


@memoize('addons:creatured', time=60 * 10)
def get_creatured_ids(category, lang):
    from addons.models import Addon
    from bandwagon.models import FeaturedCollection
    if lang:
        lang = lang.lower()
    per_locale = set()

    others = (Addon.objects
              .filter(
                  Q(collections__featuredcollection__locale__isnull=True) |
                  Q(collections__featuredcollection__locale=''),
                  collections__featuredcollection__isnull=False,
                  category=category)
              .distinct()
              .values_list('id', flat=True))

    if lang is not None and lang != '':
        possible_lang_match = FeaturedCollection.objects.filter(
            locale__icontains=lang,
            collection__addons__category=category).distinct()
        for fc in possible_lang_match:
            if lang in fc.locale.lower().split(','):
                per_locale.update(
                    fc.collection.addons
                    .filter(category=category)
                    .values_list('id', flat=True))

    others = list(others)
    per_locale = list(per_locale)
    random.shuffle(others)
    random.shuffle(per_locale)
    return map(int, filter(None, per_locale + others))
