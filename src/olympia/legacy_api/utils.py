import re

from django.conf import settings
from django.utils.html import strip_tags

from olympia import amo
from olympia.amo.helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams, epoch
from olympia.tags.models import Tag
from olympia.versions.compare import version_int


# For app version major.minor matching.
m_dot_n_re = re.compile(r'^\d+\.\d+$')


def addon_to_dict(addon, disco=False, src='api'):
    """
    Renders an addon in JSON for the API.
    """
    def url(u, **kwargs):
        return settings.SITE_URL + urlparams(u, **kwargs)

    v = addon.current_version

    if disco:
        learnmore = settings.SERVICES_URL + reverse('discovery.addons.detail',
                                                    args=[addon.slug])
        learnmore = urlparams(learnmore, src='discovery-personalrec')
    else:
        learnmore = url(addon.get_url_path(), src=src)

    d = {
        'id': addon.id,
        'name': unicode(addon.name) if addon.name else None,
        'guid': addon.guid,
        'status': amo.STATUS_CHOICES_API[addon.status],
        'type': amo.ADDON_SLUGS_UPDATE[addon.type],
        'authors': [{'id': a.id, 'name': unicode(a.name),
                     'link': absolutify(a.get_url_path(src=src))}
                    for a in addon.listed_authors],
        'summary': (
            strip_tags(unicode(addon.summary)) if addon.summary else None),
        'description': strip_tags(unicode(addon.description)),
        'icon': addon.icon_url,
        'learnmore': learnmore,
        'reviews': url(addon.reviews_url),
        'total_dls': addon.total_downloads,
        'weekly_dls': addon.weekly_downloads,
        'adu': addon.average_daily_users,
        'created': epoch(addon.created),
        'last_updated': epoch(addon.last_updated),
        'homepage': unicode(addon.homepage) if addon.homepage else None,
        'support': unicode(addon.support_url) if addon.support_url else None,
    }
    if addon.is_persona():
        d['theme'] = addon.persona.theme_data

    if v:
        d['version'] = v.version
        d['platforms'] = [unicode(a.name) for a in v.supported_platforms]
        d['compatible_apps'] = v.compatible_apps.values()

    if addon.eula:
        d['eula'] = unicode(addon.eula)

    if addon.developer_comments:
        d['dev_comments'] = unicode(addon.developer_comments)

    if addon.takes_contributions:
        contribution = {
            'link': url(addon.contribution_url, src=src),
            'meet_developers': url(addon.meet_the_dev_url(), src=src),
            'suggested_amount': addon.suggested_amount,
        }
        d['contribution'] = contribution

    if addon.type == amo.ADDON_PERSONA:
        d['previews'] = [addon.persona.preview_url]
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


def extract_filters(term, opts=None):
    """
    Pulls all the filtering options out of the term and returns a cleaned term
    and a dictionary of filter names and filter values. Term filters override
    filters found in opts.
    """

    opts = opts or {}
    filters = {}
    params = {}

    # Type filters.
    term, addon_type = extract_from_query(term, 'type', '\w+')
    addon_type = addon_type or opts.get('addon_type')
    if addon_type:
        try:
            atype = int(addon_type)
            if atype in amo.ADDON_SEARCH_TYPES:
                filters['type'] = atype
        except ValueError:
            # `addon_type` is not a digit.
            # Try to find it in `ADDON_SEARCH_SLUGS`.
            atype = amo.ADDON_SEARCH_SLUGS.get(addon_type.lower())
            if atype:
                filters['type'] = atype

    # Platform and version filters.
    # We don't touch the filters dict for platform and version: that filtering
    # is (sadly) done by the view after ES has returned results, using
    # addon.compatible_version().
    term, platform = extract_from_query(term, 'platform', '\w+')
    params['platform'] = platform or opts.get('platform')
    term, version = extract_from_query(term, 'version', '[0-9.]+')
    params['version'] = version or opts.get('version')

    # Tag filters.
    term, tag = extract_from_query(term, 'tag', '\w+')
    if tag:
        tag = Tag.objects.filter(tag_text=tag).values_list('tag_text',
                                                           flat=True)
        if tag:
            filters['tags__in'] = list(tag)

    return (term, filters, params)


def filter_version(version, app_id):
    """
    Returns filters that can be sent to ES for app version ranges.

    If the version is a alpha, beta, or pre-release this does an exact match.
    Otherwise it will query where max >= M.Na and min <= M.N.
    """
    low = version_int(version)
    return {'appversion.%s.min__lte' % app_id: low}
