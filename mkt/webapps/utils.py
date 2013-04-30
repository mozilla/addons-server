import commonware.log

import amo
from amo.utils import find_language, no_translation


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


def app_to_dict(app, currency=None, user=None):
    """Return app data as dict for API."""
    # Sad circular import issues.
    from mkt.api.resources import PreviewResource

    cv = app.current_version
    version_data = {
        'version': getattr(cv, 'version', None),
        'release_notes': getattr(cv, 'releasenotes', None)
    }

    data = {
        'app_type': app.app_type,
        'categories': list(app.categories.values_list('pk', flat=True)),
        'content_ratings': dict([(cr.get_body().name, {
            'name': cr.get_rating().name,
            'description': unicode(cr.get_rating().description),
        }) for cr in app.content_ratings.all()]) or None,
        'current_version': version_data,
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
        'slug': app.app_slug,
    }

    if app.premium:
        try:
            data['price'] = app.premium.get_price(currency)
            data['price_locale'] = app.premium.get_price_locale(currency)
        except AttributeError:
            # Until bug 864569 gets fixed.
            log.info('Missing price data for premium app: %s' % app.pk)

    with no_translation():
        data['device_types'] = [n.api_name
                                for n in app.device_types]
    if user:
        data['user'] = {'owns': app.has_author(user,
                                               [amo.AUTHOR_ROLE_OWNER])}
    return data
