from operator import attrgetter

from django.conf import settings
from django.utils import translation

import commonware.log

import amo
from amo.helpers import absolutify
from amo.utils import find_language, no_translation
from addons.models import AddonUser
from constants.applications import DEVICE_TYPES
from market.models import Price
from users.models import UserProfile

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


def app_to_dict(app, currency=None, profile=None):
    """Return app data as dict for API."""
    # Sad circular import issues.
    from mkt.api.resources import AppResource, PreviewResource
    from mkt.developers.api import AccountResource
    from mkt.developers.models import AddonPaymentAccount

    cv = app.current_version
    version_data = {
        'version': getattr(cv, 'version', None),
        'release_notes': getattr(cv, 'releasenotes', None)
    }

    supported_locales = getattr(app.current_version, 'supported_locales', '')

    data = {
        'app_type': app.app_type,
        'categories': list(app.categories.values_list('pk', flat=True)),
        'content_ratings': dict([(cr.get_body().name, {
            'name': cr.get_rating().name,
            'description': unicode(cr.get_rating().description),
        }) for cr in app.content_ratings.all()]) or None,
        'current_version': version_data,
        'default_locale': app.default_locale,
        'image_assets': dict([(ia.slug, (ia.image_url, ia.hue))
                              for ia in app.image_assets.all()]),
        'icons': dict([(icon_size,
                        app.get_icon_url(icon_size))
                       for icon_size in (16, 48, 64, 128)]),
        'is_packaged': app.is_packaged,
        'listed_authors': [{'name': author.name}
                           for author in app.listed_authors],
        'manifest_url': app.get_manifest_url(),
        'previews': PreviewResource().dehydrate_objects(app.previews.all()),
        'premium_type': amo.ADDON_PREMIUM_API[app.premium_type],
        'public_stats': app.public_stats,
        'price': None,
        'price_locale': None,
        'ratings': {'average': app.average_rating,
                    'count': app.total_reviews},
        'regions': RegionResource().dehydrate_objects(app.get_regions()),
        'slug': app.app_slug,
        'supported_locales': (supported_locales.split(',') if supported_locales
                              else [])
    }

    data['upsell'] = False
    if app.upsell:
        upsell = app.upsell.premium
        data['upsell'] = {
            'id': upsell.id,
            'app_slug': upsell.app_slug,
            'icon_url': upsell.get_icon_url(128),
            'name': unicode(upsell.name),
            'resource_uri': AppResource().get_resource_uri(upsell),
        }

    if app.premium:
        q = AddonPaymentAccount.objects.filter(addon=app)
        if len(q) > 0 and q[0].payment_account:
            data['payment_account'] = AccountResource().get_resource_uri(
                q[0].payment_account)
        try:
            data['price'] = app.get_price(currency)
            data['price_locale'] = app.get_price_locale(currency)
        except AttributeError:
            # Until bug 864569 gets fixed.
            log.info('Missing price data for premium app: %s' % app.pk)

    with no_translation():
        data['device_types'] = [n.api_name
                                for n in app.device_types]
    if profile:
        data['user'] = {
            'developed': app.has_author(profile, [amo.AUTHOR_ROLE_OWNER]),
            'installed': app.has_installed(profile),
            'purchased': app.pk in profile.purchase_ids(),
        }

    return data


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


def es_app_to_dict(obj, currency=None, profile=None):
    """
    Return app data as dict for API where `app` is the elasticsearch result.
    """
    # Circular import.
    from mkt.api.base import GenericObject
    from mkt.api.resources import AppResource, PrivacyPolicyResource
    from mkt.developers.api import AccountResource
    from mkt.developers.models import AddonPaymentAccount
    from mkt.webapps.models import Installed, Webapp

    src = obj._source
    # The following doesn't perform a database query, but gives us useful
    # methods like `get_detail_url`. If you use `obj` make sure the calls
    # don't query the database.
    is_packaged = src['app_type'] == amo.ADDON_WEBAPP_PACKAGED
    app = Webapp(app_slug=obj.app_slug, is_packaged=is_packaged)

    attrs = ('content_ratings', 'current_version', 'default_locale',
             'homepage', 'manifest_url', 'previews', 'ratings', 'status',
             'support_email', 'support_url')
    data = dict(zip(attrs, attrgetter(*attrs)(obj)))
    data.update({
        'absolute_url': absolutify(app.get_detail_url()),
        'app_type': app.app_type,
        'categories': [c for c in obj.category],
        'description': get_attr_lang(src, 'description', obj.default_locale),
        'device_types': [DEVICE_TYPES[d].api_name for d in src['device']],
        'icons': dict((i['size'], i['url']) for i in src['icons']),
        'id': str(obj._id),
        'is_packaged': is_packaged,
        'listed_authors': [{'name': name} for name in src['authors']],
        'name': get_attr_lang(src, 'name', obj.default_locale),
        'premium_type': amo.ADDON_PREMIUM_API[src['premium_type']],
        'privacy_policy': PrivacyPolicyResource().get_resource_uri(
            GenericObject({'pk': obj._id})
        ),
        'public_stats': obj.has_public_stats,
        'summary': get_attr_lang(src, 'summary', obj.default_locale),
        'slug': obj.app_slug,
    })

    data['regions'] = RegionResource().dehydrate_objects(
        map(REGIONS_CHOICES_ID_DICT.get,
            app.get_region_ids(worldwide=True,
                               excluded=obj.region_exclusions)))

    if src['premium_type'] in amo.ADDON_PREMIUMS:
        acct = list(AddonPaymentAccount.objects.filter(addon=app))
        if acct and acct.payment_account:
            data['payment_account'] = AccountResource().get_resource_uri(
                acct.payment_account)
    else:
        data['payment_account'] = None

    try:
        price = Price.objects.get(name=src['price_tier'])
        data['price'] = price.get_price(currency=currency)
        data['price_locale'] = price.get_price_locale(currency=currency)
    except Price.DoesNotExist:
        data['price'] = data['price_locale'] = None

    data['upsell'] = False
    if hasattr(obj, 'upsell'):
        data['upsell'] = obj.upsell
        data['upsell']['resource_uri'] = AppResource().get_resource_uri(
            Webapp(id=obj.upsell['id']))

    # TODO: Let's get rid of these from the API to avoid db hits.
    if profile and isinstance(profile, UserProfile):
        data['user'] = {
            'developed': AddonUser.objects.filter(
                user=profile, role=amo.AUTHOR_ROLE_OWNER).exists(),
            'installed': Installed.objects.filter(
                user=profile, addon_id=obj.id).exists(),
            'purchased': obj.id in profile.purchase_ids(),
        }

    return data
