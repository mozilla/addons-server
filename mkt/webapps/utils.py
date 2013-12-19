# -*- coding: utf-8 -*-
from collections import defaultdict

from django.conf import settings

import commonware.log
import waffle

import amo
from addons.models import AddonUser
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import find_language
from constants.applications import DEVICE_TYPES
from market.models import Price
from users.models import UserProfile

import mkt
from mkt.regions import REGIONS_CHOICES_ID_DICT


log = commonware.log.getLogger('z.webapps')


def get_locale_properties(manifest, property, default_locale=None):
    locale_dict = {}
    for locale in manifest.get('locales', {}):
        if property in manifest['locales'][locale]:
            locale_dict[locale] = manifest['locales'][locale][property]

    # Add in the default locale name.
    default = manifest.get('default_locale') or default_locale
    root_property = manifest.get(property)
    if default and root_property:
        locale_dict[default] = root_property

    return locale_dict


def get_supported_locales(manifest):
    """
    Returns a list of locales found in the "locales" property of the manifest.

    This will convert locales found in the SHORTER_LANGUAGES setting to their
    full locale. It will also remove locales not found in AMO_LANGUAGES.

    Note: The default_locale is not included.

    """
    return sorted(filter(None, map(find_language, set(
        manifest.get('locales', {}).keys()))))


def get_translations(src, attr, default_locale, lang):
    """
    Return dict of localized strings for attr or string if lang provided.

    If lang is provided, try to get the attr localized in lang, falling back to
    the app's default_locale and server language.

    If lang is not provided, we return all localized strings in the form::

        {"en": "English", "es": "Español"}

    """
    translations = src.get(attr, {})
    requested_language = find_language(lang)

    # If a language was requested, return only that translation.
    if requested_language:
        return (translations.get(requested_language) or
                translations.get(default_locale) or
                translations.get(settings.LANGUAGE_CODE) or u'')
    else:
        return translations or None


def es_app_to_dict(obj, region=None, profile=None, request=None):
    """
    Return app data as dict for API where `app` is the elasticsearch result.
    """
    # Circular import.
    from mkt.developers.models import AddonPaymentAccount
    from mkt.webapps.models import Installed, Webapp

    translation_fields = ('banner_message', 'description', 'homepage', 'name',
                          'release_notes', 'support_email', 'support_url')
    lang = None
    if request and request.method == 'GET' and 'lang' in request.GET:
        lang = request.GET.get('lang', '').lower()

    src = obj._source
    # The following doesn't perform a database query, but gives us useful
    # methods like `get_detail_url`. If you use `obj` make sure the calls
    # don't query the database.
    is_packaged = src.get('app_type') != amo.ADDON_WEBAPP_HOSTED
    app = Webapp(app_slug=obj.app_slug, is_packaged=is_packaged)

    attrs = ('created', 'current_version', 'default_locale', 'is_offline',
             'manifest_url', 'previews', 'reviewed', 'ratings', 'status',
             'weekly_downloads')
    data = dict((a, getattr(obj, a, None)) for a in attrs)

    # Flatten the localized fields from {'lang': ..., 'string': ...}
    # to {lang: string}.
    for field in translation_fields:
        src_field = '%s_translations' % field
        value_field = src.get(src_field)
        src[src_field] = dict((v.get('lang', ''), v.get('string', ''))
                              for v in value_field) if value_field else {}
        data[field] = get_translations(src, src_field, obj.default_locale,
                                       lang)

    if getattr(obj, 'content_ratings', None):
        for region_key in obj.content_ratings:
            obj.content_ratings[region_key] = dehydrate_content_rating(
                obj.content_ratings[region_key], region_key)

    data.update({
        'absolute_url': absolutify(app.get_detail_url()),
        'app_type': app.app_type,
        'author': src.get('author', ''),
        'banner_regions': src.get('banner_regions', []),
        'categories': [c for c in obj.category],
        'content_ratings': {
            'ratings': getattr(obj, 'content_ratings', {}),
            'descriptors': dehydrate_descriptors(
                getattr(obj, 'content_descriptors', {})),
            'interactive_elements': dehydrate_interactives(
                getattr(obj, 'interactive_elements', [])),
        },
        'device_types': [DEVICE_TYPES[d].api_name for d in src.get('device')],
        'icons': dict((i['size'], i['url']) for i in src.get('icons')),
        'id': long(obj._id),
        'is_packaged': is_packaged,
        'payment_required': False,
        'premium_type': amo.ADDON_PREMIUM_API[src.get('premium_type')],
        'privacy_policy': reverse('app-privacy-policy-detail',
                                  kwargs={'pk': obj._id}),
        'public_stats': obj.has_public_stats,
        'supported_locales': src.get('supported_locales', ''),
        'slug': obj.app_slug,
        # TODO: Remove the type check once this code rolls out and our indexes
        # aren't between mapping changes.
        'versions': dict((v.get('version'), v.get('resource_uri')) for v in
                         src.get('versions') if type(v) == dict),
    })

    if not data['public_stats']:
        data['weekly_downloads'] = None
    def serialize_region(o):
        d = {}
        for field in ('name', 'slug', 'mcc', 'adolescent'):
            d[field] = getattr(o, field, None)
        return d
    data['regions'] = [serialize_region(REGIONS_CHOICES_ID_DICT.get(k))
                       for k in app.get_region_ids(
                               worldwide=True,
                               excluded=obj.region_exclusions)]

    if src.get('premium_type') in amo.ADDON_PREMIUMS:
        acct = list(AddonPaymentAccount.objects.filter(addon=app))
        if acct and acct.payment_account:
            data['payment_account'] = reverse(
                'payment-account-detail',
                kwargs={'pk': acct.payment_account.pk})
    else:
        data['payment_account'] = None

    data['upsell'] = False
    if hasattr(obj, 'upsell'):
        exclusions = obj.upsell.get('region_exclusions')
        if exclusions is not None and region not in exclusions:
            data['upsell'] = obj.upsell
            data['upsell']['resource_uri'] = reverse(
                'app-detail',
                kwargs={'pk': obj.upsell['id']})

    data['price'] = data['price_locale'] = None
    try:
        price_tier = src.get('price_tier')
        if price_tier:
            price = Price.objects.get(name=price_tier)
            price_currency = price.get_price_currency(region=region)
            if price_currency and price_currency.paid:
                data['price'] = price.get_price(region=region)
                data['price_locale'] = price.get_price_locale(
                    region=region)
            data['payment_required'] = bool(price.price)
    except Price.DoesNotExist:
        log.warning('Issue with price tier on app: {0}'.format(obj._id))
        data['payment_required'] = True

    # TODO: Let's get rid of these from the API to avoid db hits.
    if profile and isinstance(profile, UserProfile):
        data['user'] = {
            'developed': AddonUser.objects.filter(
                addon=obj.id, user=profile,
                role=amo.AUTHOR_ROLE_OWNER).exists(),
            'installed': Installed.objects.filter(
                user=profile, addon_id=obj.id).exists(),
            'purchased': obj.id in profile.purchase_ids(),
        }

    return data


def dehydrate_content_rating(rating, region=None):
    """
    {body.id, rating.id} to translated {rating labels, names, descriptions}.
    """
    if (not waffle.switch_is_active('iarc') and
        region not in [_region.slug for _region in
                       mkt.regions.ALL_REGIONS_WITH_CONTENT_RATINGS()]):
        # Ratings only enabled for Brazil and Germany before IARC work.
        # When removing this waffle switch, remove the whole `if`
        # clause.
        return

    try:
        body = mkt.ratingsbodies.dehydrate_ratings_body(
            mkt.ratingsbodies.RATINGS_BODIES[int(rating['body'])])
    except TypeError:
        # Legacy ES format (bug 943371).
        return {}

    rating = mkt.ratingsbodies.dehydrate_rating(
        body.ratings[int(rating['rating'])])

    return {
        'body': unicode(body.name),
        'body_label': body.label,
        'rating': rating.name,
        'rating_label': rating.label,
        'description': rating.description
    }


def dehydrate_descriptors(keys):
    """
    List of keys to lists of objects (desc label, desc name) by body.

    ['ESRB_BLOOD, ...] to
    {'esrb': [{'label': 'blood', 'name': 'Blood'}], ...}.
    """
    results = defaultdict(list)
    for key in keys:
        obj = mkt.ratingdescriptors.RATING_DESCS.get(key)
        if obj:
            # Slugify and remove body prefix.
            body, label = key.lower().replace('_', '-').split('-', 1)
            results[body].append({
                'label': label,
                'name': unicode(obj['name']),
            })
    return results


def dehydrate_interactives(keys):
    """
    List of keys to list of objects (label, name).

    ['SOCIAL_NETWORKING', ...] to
    [{'label': 'social-networking', 'name': 'Facebocks'}, ...].
    """
    results = []
    for key in keys:
        obj = mkt.ratinginteractives.RATING_INTERACTIVES.get(key)
        if obj:
            results.append({
                'label': key.lower().replace('_', '-'),
                'name': unicode(obj['name']),
            })
    return results
