import amo
from amo.utils import no_translation


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


def app_to_dict(app, user=None):
    """Return app data as dict for API."""
    cv = app.current_version
    version_data = {
        'version': getattr(cv, 'version', None),
        'release_notes': getattr(cv, 'releasenotes', None)
    }

    data = {
        'app_slug': app.app_slug,
        'app_type': app.app_type,
        'categories': list(app.categories.values_list('pk', flat=True)),
        'content_ratings': dict([(cr.get_body().name, {
            'name': cr.get_rating().name,
            'description': unicode(cr.get_rating().description),
        }) for cr in app.content_ratings.all()]),
        'current_version': version_data,
        'image_assets': dict([(ia.slug, (ia.image_url, ia.hue))
                              for ia in app.image_assets.all()]),
        'icons': dict([(icon_size,
                        app.get_icon_url(icon_size))
                       for icon_size in (16, 48, 64, 128)]),
        'is_packaged': app.is_packaged,
        'listed_authors': [{'name': author.name}
                           for author in app.listed_authors],
        'manifest_url': app.manifest_url,
        'previews': [{'caption': pr.caption, 'full_url': pr.image_url,
                      'thumb_url': pr.thumbnail_url}
                     for pr in app.previews.all()],
        'premium_type': amo.ADDON_PREMIUM_API[app.premium_type],
        'public_stats': app.public_stats,
        'price': app.get_price(),
        'ratings': {'average': app.average_rating,
                    'count': app.total_reviews},
    }

    with no_translation():
        data['device_types'] = [n.api_name
                                for n in app.device_types]
    if user:
        data['user'] = {'owns': app.has_author(user,
                                               [amo.AUTHOR_ROLE_OWNER])}
    return data
