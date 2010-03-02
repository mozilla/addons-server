import re

from django.conf import settings
from django.utils import translation

import amo
import amo.models
from addons.models import Addon, Category
from .sphinxapi import SphinxClient
import sphinxapi as sphinx
from .utils import convert_version, crc32

m_dot_n_re = re.compile(r'^\d+\.\d+$')
SEARCH_ENGINE_APP = 99


def get_category_id(category, application):
    """
    Given a string, get the category id associated with it.
    """
    category = Category.objects.filter(
            slug__istartswith=category,
            application=application)[:1]

    if len(category):
        return category[0].id


def extract_from_query(term, filter, regexp, options={}):
    """
    This pulls out a keyword filter from a search term and returns the value
    for the filter and a new term with the filter removed.

    E.g. "yslow version:3" will result in (yslow, 3).  Failing this, we'll look
    in the search options dictionary to see if there is a value.
    """
    match = re.search(r'\b%s:\s*(%s)\b' % (filter, regexp), term)

    if match:
        term = term.replace(match.group(0), '')
        value = match.group(1)
    else:
        value = options.get(filter, None)
    return (term, value)


class SearchError(Exception):
    pass


class Client(object):
    """
    A search client that queries sphinx for addons.
    """

    def __init__(self):
        self.sphinx = SphinxClient()
        self.sphinx.SetServer(settings.SPHINX_HOST, settings.SPHINX_PORT)

    def restrict_version(self, version):
        """
        Restrict a search to a specific version.

        We can make the search a little fuzzy so that 3.7 includes
        pre-releases.
        This is done by using a high_int and a low_int.  For alpha/pre-release
        searches we assume the search needs to be specific.
        """

        sc = self.sphinx

        high_int = convert_version(version)
        low_int = high_int

        if m_dot_n_re.match(version):
            low_int = convert_version(version + "apre")

        # SetFilterRange requires a max and min even if you just want a
        # lower-bound.  To work-around this limitation we set max_ver's
        # upperbound to be ridiculously large (10x the high_int).

        if high_int:
            sc.SetFilterRange('max_ver', low_int, 10 * high_int)
            sc.SetFilterRange('min_ver', 0, high_int)

    def query(self, term, limit=10, offset=0, **kwargs):
        """
        Queries sphinx for a term, and parses specific options.

        The following kwargs will do things:

        limit: limits the number of results.  Default is 2000.
        admin: if present we are in "admin" mode which lets you find addons
            without files and overrides any 'xenophobia' settings.
        type: specifies an addon_type by id
        sort: specifies a specific sort mode.  acceptable values are 'newest',
            'updated, 'name', 'averagerating' or 'weeklydownloads'.  If no
            sort mode is specified we use relevance.
        'app': specifies which application_id to limit searches by
        'version': specifies which version of an app (as specified) that
            addons need to be compatble
        'xenophobia': restricts addons to the users own locale
        'locale': restricts addons to the specified locale

        """

        sc = self.sphinx

        # Setup some default parameters for the search.
        fields = "addon_id, app, category"

        sc.SetSelect(fields)
        sc.SetFieldWeights({'name': 4})
        # limiting happens later, since Sphinx returns more than we need.
        sc.SetLimits(0, 2000)
        sc.SetFilter('inactive', (0,))

        # STATUS_DISABLED and 0 (which likely means null) are filtered from
        # search

        sc.SetFilter('addon_status', (0, amo.STATUS_DISABLED), True)

        # Status filtering

        if 'status' in kwargs:
            if not isinstance(kwargs['status'], list):
                kwargs['status'] = [kwargs['status']]

            sc.SetFilter('addon_status', kwargs['status'])

        # Unless we're in admin mode, or we're looking at stub entries,
        # everything must have a file.
        if (('admin' not in kwargs) and
            ('type' not in kwargs or kwargs['type'] != amo.ADDON_PERSONA)):
            sc.SetFilter('num_files', (0,), True)

        # Sorting
        if 'sort' in kwargs:
            if kwargs['sort'] == 'newest':
                sc.SetSortMode(sphinx.SPH_SORT_ATTR_DESC, 'created')
            elif kwargs['sort'] == 'updated':
                sc.SetSortMode(sphinx.SPH_SORT_ATTR_DESC, 'modified')
            elif kwargs['sort'] == 'name':
                sc.SetSortMode(sphinx.SPH_SORT_ATTR_ASC, 'name_ord')
            elif (kwargs['sort'] == 'averagerating' or
                kwargs['sort'] == 'bayesianrating'):
                sc.SetSortMode(sphinx.SPH_SORT_ATTR_DESC, 'averagerating')
            elif kwargs['sort'] == 'weeklydownloads':
                sc.SetSortMode(sphinx.SPH_SORT_ATTR_DESC, 'weeklydownloads')

        else:
            # We want to boost public addons, and addons in your native
            # language.
            expr = ("@weight + IF(addon_status=%d, 30, 0) + "
                "IF(locale_ord=%d, 29, 0)") % (amo.STATUS_PUBLIC,
                crc32(translation.get_language()))
            sc.SetSortMode(sphinx.SPH_SORT_EXPR, expr)

        # We should always have an 'app' except for the admin.
        if 'app' in kwargs:
            # We add SEARCH_ENGINE_APP since search engines work on all apps.
            sc.SetFilter('app', (kwargs['app'], SEARCH_ENGINE_APP))

        # Version filtering.
        (term, version) = extract_from_query(term, 'version', '[0-9.]+',
                                             kwargs)

        if version:
            self.restrict_version(version)

        # Category filtering.
        (term, category) = extract_from_query(term, 'category', '\w+')

        if category and 'app' in kwargs:
            category = get_category_id(category, kwargs['app'])
            if category:
                sc.SetFilter('category', [int(category)])

        (term, platform) = extract_from_query(term, 'platform', '\w+', kwargs)

        if platform:
            platform = amo.PLATFORMS.get(platform)
            if platform:
                sc.SetFilter('platform', (int(platform), amo.PLATFORM_ALL,))

        (term, addon_type) = extract_from_query(term, 'type', '\w+', kwargs)

        if addon_type:
            if not isinstance(addon_type, int):
                types = dict((name.lower(), id) for id, name
                             in amo.ADDON_TYPE.items())
                addon_type = types.get(addon_type.lower())
            if addon_type:
                sc.SetFilter('type', (addon_type,))

        # Xenophobia - restrict to just my language.
        if 'xenophobia' in kwargs and 'admin' not in kwargs:
            kwargs['locale'] = translation.get_language()

        # Locale filtering
        if 'locale' in kwargs:
            sc.SetFilter('locale_ord', (crc32(kwargs['locale']),))

        # XXX - Todo:
        # In the interest of having working code sooner than later, we're
        # skipping the following... for now:
        #   * Date filter
        #   * GUID filter
        #   * Tag filter
        #   * Num apps filter
        #   * Logging

        result = sc.Query(term)
        self.total_found = result['total_found'] if result else 0

        if sc.GetLastError():
            raise SearchError(sc.GetLastError())
        if result and result['total']:
            # Return results as a list of addons.
            results = [m['attrs']['addon_id'] for m in result['matches']]

            # Uniquify
            ids = []
            for the_id in results:
                if the_id not in ids:
                    ids.append(the_id)

            ids = ids[offset:limit]
            addons = Addon.objects.filter(id__in=ids).extra(
                    select={'manual': 'FIELD(id,%s)'
                            % ','.join(map(str, ids))},
                    order_by=['manual'])

            return addons
        else:
            return []
