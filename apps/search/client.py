import re

from django.conf import settings
from django.utils import translation

import amo.models
from .sphinxapi import SphinxClient
import sphinxapi as sphinx
from .utils import convert_version, crc32

m_dot_n_re = re.compile(r'^\d+\.\d+$')
SEARCH_ENGINE_APP = 99


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

    def query(self, term, **kwargs):
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

        limit = kwargs.get('limit', 2000)

        sc.SetSelect(fields)
        sc.SetFieldWeights({'name': 4})
        sc.SetLimits(0, limit)
        sc.SetFilter('inactive', (0,))

        # STATUS_DISABLED and 0 (which likely means null) are filtered from
        # search

        sc.SetFilter('status', (0, amo.STATUS_DISABLED), True)

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
            expr = ("@weight + IF(status=%d, 30, 0) + "
                "IF(locale_ord=%d, 29, 0)") % (amo.STATUS_PUBLIC,
                crc32(translation.get_language()))
            sc.SetSortMode(sphinx.SPH_SORT_EXPR, expr)

        # We should always have an 'app' except for the admin.
        if 'app' in kwargs:
            # We add SEARCH_ENGINE_APP since search engines work on all apps.
            sc.SetFilter('app', (kwargs['app'], SEARCH_ENGINE_APP))

        # Version filtering.
        match = re.match('\bversion:([0-9\.]+)/', term)

        if match:
            term = term.replace(match.group(0), '')
            self.restrict_version(match.group(1))
        elif 'version' in kwargs:
            self.restrict_version(kwargs['version'])

        # Xenophobia - restrict to just my language.
        if 'xenophobia' in kwargs and 'admin' not in kwargs:
            kwargs['locale'] = translation.get_language()

        # Locale filtering
        if 'locale' in kwargs:
            sc.SetFilter('locale_ord', (crc32(kwargs['locale']),))

        # XXX - Todo:
        # In the interest of having working code sooner than later, we're
        # skipping the following... for now:
        #   * Type filter
        #   * Platform filter
        #   * Date filter
        #   * GUID filter
        #   * Category filter
        #   * Tag filter
        #   * Num apps filter
        #   * Logging

        result = sc.Query(term)

        if result:
            return result['matches']
