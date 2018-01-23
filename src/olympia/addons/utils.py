import random
import uuid

from django import forms
from django.core.cache import cache
from django.db.models import Q
from django.utils.translation import ugettext

import olympia.core.logger

from olympia import amo
from olympia.amo.cache_nuggets import memoize, memoize_key
from olympia.translations.fields import LocaleList, LocaleValidationError
from olympia.constants.categories import CATEGORIES_BY_ID


log = olympia.core.logger.getLogger('z.redis')


def generate_addon_guid():
    return '{%s}' % str(uuid.uuid4())


def clear_get_featured_ids_cache(*args, **kwargs):
    cache_key = memoize_key('addons:featured', *args, **kwargs)
    cache.delete(cache_key)


@memoize('addons:featured', time=60 * 10)
def get_featured_ids(app=None, lang=None, type=None):
    from olympia.addons.models import Addon
    ids = []
    is_featured = Q(collections__featuredcollection__isnull=False)
    if app:
        is_featured &= Q(collections__featuredcollection__application=app.id)
    qs = Addon.objects.valid()

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
def get_creatured_ids(category, lang=None):
    from olympia.addons.models import Addon
    from olympia.bandwagon.models import FeaturedCollection
    if lang:
        lang = lang.lower()
    per_locale = set()
    if isinstance(category, int):
        category = CATEGORIES_BY_ID[category]
    app_id = category.application

    others = (Addon.objects.public()
              .filter(
                  Q(collections__featuredcollection__locale__isnull=True) |
                  Q(collections__featuredcollection__locale=''),
                  collections__featuredcollection__isnull=False,
                  collections__featuredcollection__application=app_id,
                  category=category.id)
              .distinct()
              .values_list('id', flat=True))

    if lang is not None and lang != '':
        possible_lang_match = FeaturedCollection.objects.filter(
            locale__icontains=lang,
            application=app_id,
            collection__addons__category=category.id).distinct()
        for fc in possible_lang_match:
            if lang in fc.locale.lower().split(','):
                per_locale.update(
                    fc.collection.addons
                    .filter(category=category.id)
                    .values_list('id', flat=True))

    others = list(others)
    per_locale = list(per_locale)
    random.shuffle(others)
    random.shuffle(per_locale)
    return map(int, filter(None, per_locale + others))


def verify_mozilla_trademark(name, user):
    skip_trademark_check = (
        user and user.is_authenticated() and
        user.email.endswith(amo.ALLOWED_TRADEMARK_SUBMITTING_EMAILS))

    def _check(name):
        name = name.lower()
        violates_trademark = (
            any(symbol in name for symbol in amo.MOZILLA_TRADEMARK_SYMBOLS)
            and not name.endswith(tuple(
                'for {}'.format(symbol)
                for symbol in amo.MOZILLA_TRADEMARK_SYMBOLS)))

        if violates_trademark:
            raise forms.ValidationError(ugettext(
                        u'Add-on names cannot contain the Mozilla or '
                        u'Firefox trademarks. These names should not be '
                        u'contained in add-on names if at all possible.'))


    if not skip_trademark_check:
        errors = LocaleList()

        if not isinstance(name, dict):
            _check(name)
        else:
            for locale, localized_name in name.items():
                try:
                    _check(localized_name)
                except forms.ValidationError as exc:
                    errors.extend(exc.messages, locale)

        if errors:
            raise LocaleValidationError(errors)

    return name
