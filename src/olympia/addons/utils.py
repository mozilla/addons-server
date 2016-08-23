import uuid
import logging
import random

from django.db.models import Q

import commonware.log
from cache_nuggets.lib import memoize


log = commonware.log.getLogger('z.redis')
rnlog = logging.getLogger('z.rn')


def generate_addon_guid():
    return '{%s}' % str(uuid.uuid4())


def reverse_name_lookup(key, addon_type, instance=None):
    """Does a reverse lookup by localized add-on name.

    If `key` is a dictionary we assume it's a localized mapping of

    .. code-block::

        {'en-us': 'Bands Make You Dance'}

    :returns: `True` or `False` related to whether or not we can find an add-on
    """
    from olympia.addons.models import Addon

    has_instance = instance is not None and instance.id is not None

    # This uses the Addon.objects manager, which filters out unlisted addons,
    # on purpose. We don't want to enforce name uniqueness between listed and
    # unlisted addons.
    if isinstance(key, dict):
        # We are looking up translations so let's check them all
        filter = Q()

        for locale, localized_key in key.items():
            filter |= Q(
                name__localized_string=localized_key,
                name__locale=locale,
                type=addon_type)
    else:
        filter = Q(name__localized_string=key, type=addon_type)

    if has_instance:
        filter = filter & ~Q(id=instance.id)

    return Addon.objects.filter(filter).exists()


@memoize('addons:featured', time=60 * 10)
def get_featured_ids(app, lang=None, type=None):
    from olympia.addons.models import Addon
    ids = []
    is_featured = (Q(collections__featuredcollection__isnull=False) &
                   Q(collections__featuredcollection__application=app.id))
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
    from olympia.addons.models import Addon
    from olympia.bandwagon.models import FeaturedCollection
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
