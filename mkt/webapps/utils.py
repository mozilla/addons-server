# -*- coding: utf-8 -*-
from collections import defaultdict

from django.conf import settings

import commonware.log

import amo
from addons.models import AddonUser, Preview
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import find_language
from constants.applications import DEVICE_TYPES
from market.models import Price
from users.models import UserProfile

import mkt
from mkt.regions import get_region, REGIONS_CHOICES_ID_DICT, REGION_LOOKUP


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


def es_app_to_dict(obj, profile=None, request=None):
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

    if hasattr(request, 'REGION'):
        region_slug = request.REGION.slug
        region_id = request.REGION.id
    else:
        region_slug = None
        region_id = None

    src = obj._source
    is_packaged = src.get('app_type') != amo.ADDON_WEBAPP_HOSTED
    # The following doesn't perform a database query, but gives us useful
    # methods like `get_detail_url` and `get_icon_url`. If you use `app` make
    # sure the calls don't query the database.
    app = Webapp(id=obj._id, app_slug=obj.app_slug, is_packaged=is_packaged,
                 type=amo.ADDON_WEBAPP, icon_type='image/png',
                 modified=getattr(obj, 'modified', None))

    attrs = ('created', 'current_version', 'default_locale', 'is_offline',
             'manifest_url', 'reviewed', 'ratings', 'status',
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

    # Generate urls for previews and icons before the data.update() call below
    # adds them to the result.
    previews = getattr(obj, 'previews', [])
    for preview in previews:
        if 'image_url' and 'thumbnail_url' in preview:
            # Old-style index, the full URL is already present, nothing to do.
            # TODO: remove this check once we have re-indexed everything.
            continue
        else:
            # New-style index, we need to build the URLs from the data we have.
            p = Preview(id=preview.pop('id'), modified=preview.pop('modified'),
                        filetype=preview['filetype'])
            preview['image_url'] = p.image_url
            preview['thumbnail_url'] = p.thumbnail_url
    icons = getattr(obj, 'icons', [])
    for icon in icons:
        if 'url' in icon:
            # Old-style index, the full URL is already present, nothing to do.
            # TODO: remove this check once we have re-indexed everything.
            continue
        else:
            # New-style index, we need to build the URLs from the data we have.
            icon['url'] = app.get_icon_url(icon['size'])

    data.update({
        'absolute_url': absolutify(app.get_detail_url()),
        'app_type': 'packaged' if is_packaged else 'hosted',
        'author': src.get('author', ''),
        'banner_regions': src.get('banner_regions', []),
        'categories': [c for c in obj.category],
        'content_ratings': filter_content_ratings_by_region({
            'ratings': dehydrate_content_ratings(
                getattr(obj, 'content_ratings', {})),
            'descriptors': dehydrate_descriptors(
                getattr(obj, 'content_descriptors', {})),
            'interactive_elements': dehydrate_interactives(
                getattr(obj, 'interactive_elements', [])),
            'regions': mkt.regions.REGION_TO_RATINGS_BODY()
        }, region=region_slug),
        'device_types': [DEVICE_TYPES[d].api_name for d in src.get('device')],
        'icons': dict((i['size'], i['url']) for i in src.get('icons')),
        'id': long(obj._id),
        'is_packaged': is_packaged,
        'payment_required': False,
        'premium_type': amo.ADDON_PREMIUM_API[src.get('premium_type')],
        'previews': previews,
        'privacy_policy': reverse('app-privacy-policy-detail',
                                  kwargs={'pk': obj._id}),
        'public_stats': obj.has_public_stats,
        'supported_locales': src.get('supported_locales', ''),
        'slug': obj.app_slug,
        'versions': dict((v.get('version'), v.get('resource_uri')) for v in
                         src.get('versions')),
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
                           restofworld=True, excluded=obj.region_exclusions)]

    data['payment_account'] = None
    if src.get('premium_type') in amo.ADDON_PREMIUMS:
        try:
            acct = AddonPaymentAccount.objects.get(addon_id=src.get('id'))
            if acct.payment_account:
                data['payment_account'] = reverse(
                    'payment-account-detail',
                    kwargs={'pk': acct.payment_account.pk})
        except AddonPaymentAccount.DoesNotExist:
            pass  # Developer hasn't set up a payment account yet.

    data['upsell'] = False
    if hasattr(obj, 'upsell'):
        exclusions = obj.upsell.get('region_exclusions')
        if exclusions is not None and region_slug not in exclusions:
            data['upsell'] = obj.upsell
            data['upsell']['resource_uri'] = reverse(
                'app-detail',
                kwargs={'pk': obj.upsell['id']})

    data['price'] = data['price_locale'] = None
    try:
        price_tier = src.get('price_tier')
        if price_tier:
            price = Price.objects.get(name=price_tier)
            price_currency = price.get_price_currency(region=region_id)
            if price_currency and price_currency.paid:
                data['price'] = price.get_price(region=region_id)
                data['price_locale'] = price.get_price_locale(
                    region=region_id)
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


def dehydrate_content_rating(rating):
    """
    {body.id, rating.id} to translated {rating labels, names, descriptions}.
    """
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


def dehydrate_content_ratings(content_ratings):
    """Dehydrate an object of content ratings from rating IDs to dict."""
    for body in content_ratings or {}:
        # Dehydrate all content ratings.
        content_ratings[body] = dehydrate_content_rating(content_ratings[body])
    return content_ratings


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
    return dict(results)


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


def _filter_iarc_obj_by_region(obj, region=None, lookup_body=False):
    """
    Given an object keyed by ratings bodies, filter out ratings bodies that
    aren't used by the passed in region slug.

    (e.g. _filter_iarc({'esrb': ESRB_RATING, 'classind': CLASSIND_RATING},
                       region='br', lookup_body=True)
          returns just {'esrb': ESRB_RATING}.

    region -- region slug to filter by.
    lookup_body -- whether we want to fetch the ratings body slug associated w/
                   the region.
    """
    regions_to_ratings = mkt.regions.REGION_TO_RATINGS_BODY()
    generic = mkt.regions.GENERIC_RATING_REGION_SLUG  # 'generic'.

    if obj and region and region in regions_to_ratings:
        if lookup_body:  # Or filter by rating body slug.
            body_slug = regions_to_ratings.get(region, generic)
            if body_slug in obj:
                return {body_slug: obj[body_slug]}
            return obj
        return {region: obj.get(region, generic)}

    return obj


def filter_content_ratings_by_region(content_ratings, region=None):
    """
    Given a region, remove irrelevant stuff from the content_ratings obj.
    e.g. if given 'us' region, only filter for ESRB stuff. Slims down response.
    """
    if region:
        content_ratings['ratings'] = _filter_iarc_obj_by_region(
            content_ratings['ratings'], region=region, lookup_body=True)
        content_ratings['descriptors'] = _filter_iarc_obj_by_region(
            content_ratings['descriptors'], region=region, lookup_body=True)
        content_ratings['regions'] = _filter_iarc_obj_by_region(
            content_ratings['regions'], region=region)
    return content_ratings


def remove_iarc_exclusions(app):
    """
    Remove Germany/Brazil exclusions based on attained content ratings.
    """
    from mkt.webapps.models import Geodata
    if not Geodata.objects.filter(addon=app).exists():
        return

    geodata = app._geodata
    if geodata.region_br_iarc_exclude or geodata.region_de_iarc_exclude:
        geodata.update(region_br_iarc_exclude=False,
                       region_de_iarc_exclude=False)
        log.info('Un-excluding IARC-excluded app:%s from br/de')
