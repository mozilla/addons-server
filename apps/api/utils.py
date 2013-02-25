import re

from django.conf import settings
from django.utils.html import strip_tags

import amo
from amo.urlresolvers import reverse
from amo.utils import urlparams, epoch
from addons.models import Category
from tags.models import Tag
from versions.compare import version_int


# For app version major.minor matching.
m_dot_n_re = re.compile(r'^\d+\.\d+$')


def addon_to_dict(addon, disco=False, src='api'):
    """
    Renders an addon in JSON for the API.
    """
    v = addon.current_version
    url = lambda u, **kwargs: settings.SITE_URL + urlparams(u, **kwargs)

    if disco:
        learnmore = settings.SERVICES_URL + reverse('discovery.addons.detail',
                                                    args=[addon.slug])
        learnmore = urlparams(learnmore, src='discovery-personalrec')
    else:
        learnmore = url(addon.get_url_path(), src=src)

    d = {
         'id': addon.id,
         'name': addon.name,
         'guid': addon.guid,
         'status': addon.status,
         'type': amo.ADDON_SLUGS_UPDATE[addon.type],
         'author': (addon.listed_authors[0].name if
                    addon.listed_authors else ''),
         'summary': strip_tags(addon.summary),
         'description': strip_tags(addon.description),
         'icon': addon.icon_url,
         'learnmore': learnmore,
         'reviews': url(addon.reviews_url),
         'total_dls': addon.total_downloads,
         'weekly_dls': addon.weekly_downloads,
         'adu': addon.average_daily_users,
         'created': epoch(addon.created),
         'last_updated': epoch(addon.last_updated),
         'homepage': addon.homepage,
         'support': addon.support_url,
    }

    if v:
        d['version'] = v.version
        d['platforms'] = [a.name for a in v.supported_platforms]
        d['compatible_apps'] = v.compatible_apps.values()

    if addon.eula:
        d['eula'] = addon.eula

    if addon.developer_comments:
        d['dev_comments'] = addon.developer_comments

    if addon.takes_contributions:
        contribution = {
                'link': url(addon.contribution_url, src=src),
                'meet_developers': url(addon.meet_the_dev_url(), src=src),
                'suggested_amount': addon.suggested_amount,
                }
        d['contribution'] = contribution

    if addon.type == amo.ADDON_PERSONA:
        d['previews'] = [addon.persona.preview_url]
    elif addon.type == amo.ADDON_WEBAPP:
        d['app_type'] = (amo.ADDON_WEBAPP_PACKAGED if addon.is_packaged
                         else amo.ADDON_WEBAPP_HOSTED)
    else:
        d['previews'] = [p.as_dict(src=src) for p in addon.all_previews]

    return d


def extract_from_query(term, filter, regexp, end_of_word_boundary=True):
    """
    This pulls out a keyword filter from a search term and returns the value
    for the filter and a new term with the filter removed.

    E.g. term="yslow version:3", filter='version', regexp='\w+' will result in
    a return value of: (yslow, 3).
    """
    re_string = r'\b%s:\s*(%s)' % (filter, regexp)

    if end_of_word_boundary:
        re_string += r'\b'

    match = re.search(re_string, term)
    if match:
        term = term.replace(match.group(0), '').strip()
        value = match.group(1)
    else:
        value = None

    return (term, value)


def extract_filters(term, app_id=amo.FIREFOX.id, opts=None):
    """
    Pulls all the filtering options out of the term and returns a cleaned term
    and a dictionary of filter names and filter values. Term filters override
    filters found in opts.
    """

    opts = opts or {}
    filters = {}

    # Type filters.
    term, addon_type = extract_from_query(term, 'type', '\w+')
    addon_type = addon_type or opts.get('addon_type')
    if addon_type:
        try:
            atype = int(addon_type)
            if atype in amo.ADDON_SEARCH_TYPES:
                filters['type'] = atype
        except ValueError:
            # `addon_type` is not a digit. Try to find it in ADDON_SEARCH_SLUGS.
            atype = amo.ADDON_SEARCH_SLUGS.get(addon_type.lower())
            if atype:
                filters['type'] = atype

    # Platform filters.
    term, platform = extract_from_query(term, 'platform', '\w+')
    platform = platform or opts.get('platform')
    if platform:
        platform = [amo.PLATFORM_DICT.get(platform.lower(),
                                          amo.PLATFORM_ALL).id]
        if amo.PLATFORM_ALL.id not in platform:
            platform.append(amo.PLATFORM_ALL.id)
        filters['platform__in'] = platform

    # Version filters.
    term, version = extract_from_query(term, 'version', '[0-9.]+')
    version = version or opts.get('version')
    if version:
        filters.update(filter_version(version, app_id))

    # Category filters.
    term, category = extract_from_query(term, 'category', '\w+')
    if category and 'app' in opts:
        category = (Category.objects.filter(slug__istartswith=category,
                                            application=opts['app'])
                    .values_list('id', flat=True))
        if category:
            filters['category'] = category[0]

    # Tag filters.
    term, tag = extract_from_query(term, 'tag', '\w+')
    if tag:
        tag = Tag.objects.filter(tag_text=tag).values_list('tag_text',
                                                           flat=True)
        if tag:
            filters['tags__in'] = list(tag)

    return (term, filters)


def filter_version(version, app_id):
    """
    Returns filters that can be sent to ES for app version ranges.

    If the version is a alpha, beta, or pre-release this does an exact match.
    Otherwise it will query where max >= M.Na and min <= M.N.
    """
    low = version_int(version)
    return {'appversion.%s.min__lte' % app_id: low}
