# -*- coding: utf-8 -*-
from collections import defaultdict

import commonware.log

from amo.utils import find_language

import mkt

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
