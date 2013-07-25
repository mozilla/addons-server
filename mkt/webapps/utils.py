from django.conf import settings
from django.utils import translation

import commonware.log
import waffle

import amo
from access import acl
from addons.models import AddonUser
from amo.helpers import absolutify
from amo.utils import find_language, no_translation
from constants.applications import DEVICE_TYPES
from market.models import Price
from users.models import UserProfile
from versions.models import Version

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


def app_to_dict(app, region=None, profile=None, request=None):
    """Return app data as dict for API."""
    # Sad circular import issues.
    from mkt.api.resources import AppResource
    from mkt.developers.api import AccountResource
    from mkt.developers.models import AddonPaymentAccount
    from mkt.submit.api import PreviewResource
    from mkt.webapps.models import reverse_version

    supported_locales = getattr(app.current_version, 'supported_locales', '')

    data = {
        'app_type': app.app_type,
        'author': app.developer_name,
        'categories': list(app.categories.values_list('slug', flat=True)),
        'content_ratings': dict([(cr.get_body().name, {
            'name': cr.get_rating().name,
            'description': unicode(cr.get_rating().description),
        }) for cr in app.content_ratings.all()]) or None,
        'created': app.created,
        'current_version': (app.current_version.version if
                            getattr(app, 'current_version') else None),
        'default_locale': app.default_locale,
        'image_assets': dict([(ia.slug, (ia.image_url, ia.hue))
                              for ia in app.image_assets.all()]),
        'icons': dict([(icon_size,
                        app.get_icon_url(icon_size))
                       for icon_size in (16, 48, 64, 128)]),
        'is_packaged': app.is_packaged,
        'manifest_url': app.get_manifest_url(),
        'payment_required': False,
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
                              else []),
        'weekly_downloads': app.weekly_downloads if app.public_stats else None,
        'versions': dict((v.version, reverse_version(v)) for
                         v in app.versions.all())
    }

    data['upsell'] = False
    if app.upsell and region in settings.PURCHASE_ENABLED_REGIONS:
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

        if (region in settings.PURCHASE_ENABLED_REGIONS or
            (request and
             waffle.flag_is_active(request, 'allow-paid-app-search'))):
            data['price'] = app.get_price(region=region)
            data['price_locale'] = app.get_price_locale(region=region)
        data['payment_required'] = (bool(app.get_tier().price)
                                    if app.get_tier() else False)

    with no_translation():
        data['device_types'] = [n.api_name
                                for n in app.device_types]
    if profile:
        data['user'] = {
            'developed': app.addonuser_set.filter(
                user=profile, role=amo.AUTHOR_ROLE_OWNER).exists(),
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


def es_app_to_dict(obj, region=None, profile=None, request=None):
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
    is_packaged = src.get('app_type') == amo.ADDON_WEBAPP_PACKAGED
    app = Webapp(app_slug=obj.app_slug, is_packaged=is_packaged)

    attrs = ('content_ratings', 'created', 'current_version', 'default_locale',
             'homepage', 'manifest_url', 'previews', 'ratings', 'status',
             'support_email', 'support_url', 'versions', 'weekly_downloads')
    data = dict((a, getattr(obj, a, None)) for a in attrs)
    data.update({
        'absolute_url': absolutify(app.get_detail_url()),
        'app_type': app.app_type,
        'author': src.get('author', ''),
        'categories': [c for c in obj.category],
        'description': get_attr_lang(src, 'description', obj.default_locale),
        'device_types': [DEVICE_TYPES[d].api_name for d in src.get('device')],
        'icons': dict((i['size'], i['url']) for i in src.get('icons')),
        'id': str(obj._id),
        'is_packaged': is_packaged,
        'name': get_attr_lang(src, 'name', obj.default_locale),
        'payment_required': False,
        'premium_type': amo.ADDON_PREMIUM_API[src.get('premium_type')],
        'privacy_policy': PrivacyPolicyResource().get_resource_uri(
            GenericObject({'pk': obj._id})
        ),
        'public_stats': obj.has_public_stats,
        'supported_locales': src.get('supported_locales', ''),
        'slug': obj.app_slug,
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
            data['payment_account'] = AccountResource().get_resource_uri(
                acct.payment_account)
    else:
        data['payment_account'] = None

    data['price'] = data['price_locale'] = None
    try:
        price_tier = src.get('price_tier')
        if price_tier:
            price = Price.objects.get(name=price_tier)
            if (region in settings.PURCHASE_ENABLED_REGIONS or
                (request and
                 waffle.flag_is_active(request, 'allow-paid-app-search'))):
                data['price'] = price.get_price(region=region)
                data['price_locale'] = price.get_price_locale(region=region)
            data['payment_required'] = bool(price.price)
    except Price.DoesNotExist:
        log.warning('Issue with price tier on app: {0}'.format(obj._id))
        data['payment_required'] = True

    data['upsell'] = False
    if hasattr(obj, 'upsell') and region in settings.PURCHASE_ENABLED_REGIONS:
        data['upsell'] = obj.upsell
        data['upsell']['resource_uri'] = AppResource().get_resource_uri(
            Webapp(id=obj.upsell['id']))

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


def update_with_reviewer_data(bundle, using_es=False):
    """Adds reviewer specific data to app response bundle."""
    # TODO: Reviewer flags in ES (bug 848446)
    from editors.models import EscalationQueue

    if acl.action_allowed(bundle.request, 'Apps', 'Review'):
        # Try bundle.obj._id first if it's coming from elasticsearch.
        # Fallback to database results using `.id`.
        addon_id = getattr(bundle.obj, '_id', bundle.obj.id)

        if using_es and hasattr(bundle.obj, 'latest_version'):
            # If we know we are using elasticsearch and we have latest_version,
            # then we can directly return it in the results.
            bundle.data['latest_version'] = bundle.obj.latest_version
        else:
            version = Version.objects.filter(addon_id=addon_id).latest()
            try:
                latest_version_status = version.statuses[0][1]
            except IndexError:
                latest_version_status = None
            bundle.data['latest_version'] = {
                'status': latest_version_status,
                'is_privileged': version.is_privileged,
                'has_editor_comment': version.has_editor_comment,
                'has_info_request': version.has_info_request,
            }
        if using_es and hasattr(bundle.obj, 'is_escalated'):
            bundle.data['is_escalated'] = bundle.obj.is_escalated
        else:
            escalated = EscalationQueue.objects.filter(
                addon_id=addon_id).exists()
            bundle.data['is_escalated'] = escalated

    return bundle
