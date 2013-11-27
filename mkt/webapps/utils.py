import json

from django.conf import settings
from django.core.urlresolvers import reverse
from django.utils import translation

import commonware.log

import amo
from addons.models import AddonUser
from amo.helpers import absolutify
from amo.utils import find_language
from amo.urlresolvers import reverse
from constants.applications import DEVICE_TYPES
from market.models import Price
from users.models import UserProfile

import mkt
from mkt.purchase.utils import payments_enabled
from mkt.regions import REGIONS_CHOICES_ID_DICT
from mkt.regions.api import RegionResource

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


def get_attr_lang(src, attr, default_locale):
    """
    Our index stores localized strings in elasticsearch as, e.g.,
    "name_spanish": [u'Nombre']. This takes the current language in the
    threadlocal and gets the localized value, defaulting to
    settings.LANGUAGE_CODE.
    """
    req_lang = amo.SEARCH_LANGUAGE_TO_ANALYZER.get(
        translation.get_language().lower())
    def_lang = amo.SEARCH_LANGUAGE_TO_ANALYZER.get(
        default_locale.lower())
    svr_lang = amo.SEARCH_LANGUAGE_TO_ANALYZER.get(
        settings.LANGUAGE_CODE.lower())

    value = (src.get('%s_%s' % (attr, req_lang)) or
             src.get('%s_%s' % (attr, def_lang)) or
             src.get('%s_%s' % (attr, svr_lang)))
    return value[0] if value else u''


def es_app_to_dict(obj, region=None, profile=None, request=None):
    """
    Return app data as dict for API where `app` is the elasticsearch result.
    """
    # Circular import.
    from mkt.developers.models import AddonPaymentAccount
    from mkt.webapps.models import Installed, Webapp

    src = obj._source
    # The following doesn't perform a database query, but gives us useful
    # methods like `get_detail_url`. If you use `obj` make sure the calls
    # don't query the database.
    is_packaged = src.get('app_type') != amo.ADDON_WEBAPP_HOSTED
    app = Webapp(app_slug=obj.app_slug, is_packaged=is_packaged)

    attrs = ('created', 'current_version', 'default_locale', 'homepage',
             'is_offline', 'manifest_url', 'previews', 'ratings', 'status',
             'support_email', 'support_url', 'weekly_downloads')
    data = dict((a, getattr(obj, a, None)) for a in attrs)

    if getattr(obj, 'content_ratings', None):
        for region_key in obj.content_ratings:
            obj.content_ratings[region_key] = dehydrate_content_rating(
                obj.content_ratings[region_key])

    data.update({
        'absolute_url': absolutify(app.get_detail_url()),
        'app_type': app.app_type,
        'author': src.get('author', ''),
        'categories': [c for c in obj.category],
        'content_ratings': {
            'ratings': getattr(obj, 'content_ratings', []),
            'descriptors': dehydrate_descriptors(
                getattr(obj, 'content_descriptors', [])),
            'interactive_elements': dehydrate_interactives(
                getattr(obj, 'interactive_elements', [])),
        },
        'description': get_attr_lang(src, 'description', obj.default_locale),
        'device_types': [DEVICE_TYPES[d].api_name for d in src.get('device')],
        'icons': dict((i['size'], i['url']) for i in src.get('icons')),
        'id': str(obj._id),
        'is_packaged': is_packaged,
        'name': get_attr_lang(src, 'name', obj.default_locale),
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

    data['regions'] = RegionResource().dehydrate_objects(
        map(REGIONS_CHOICES_ID_DICT.get,
            app.get_region_ids(worldwide=True,
                               excluded=obj.region_exclusions)))

    if src.get('premium_type') in amo.ADDON_PREMIUMS:
        acct = list(AddonPaymentAccount.objects.filter(addon=app))
        if acct and acct.payment_account:
            data['payment_account'] = reverse('payment-account-detail',
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
            if (data['upsell'] or payments_enabled(request)):
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
            'developed': AddonUser.objects.filter(addon=obj.id,
                user=profile, role=amo.AUTHOR_ROLE_OWNER).exists(),
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


def dehydrate_descriptors(keys):
    """
    List of keys to list of objects (desc label, desc name, body).

    ['ESRB_BLOOD, ...] to
    [{'label': 'esrb-blood', 'name': 'Blood', 'ratings_body': 'esrb'}, ...].
    """
    results = []
    for key in keys:
        obj = mkt.ratingdescriptors.RATING_DESCS.get(key)
        if obj:
            results.append({
                'label': key.lower().replace('_', '-'),
                'name': unicode(obj['name']),
                'ratings_body': key.split('_')[0].lower()
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
