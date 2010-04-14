from collections import defaultdict
import logging
import random
import re
import socket

from django.conf import settings
from django.utils import translation
from django.utils.encoding import smart_unicode

import sphinxapi as sphinx

import amo
from amo.models import manual_order
from addons.models import Addon, Category
from translations.query import order_by_translation
from translations.transformer import get_trans
from tags.models import Tag

from .utils import convert_version, crc32

m_dot_n_re = re.compile(r'^\d+\.\d+$')
SEARCH_ENGINE_APP = 99
BIG_INTEGER = 10000000    # Used for SetFilterRange
MAX_TAGS = 10             # Number of tags we return by default.
SPHINX_HARD_LIMIT = 1000  # A hard limit that sphinx imposes.
THE_FUTURE = 9999999999

log = logging.getLogger('z.sphinx')


def extract_filters(term, kwargs):
    """Pulls all the filtering options out of kwargs and the term and
    returns a cleaned term without said options and a dictionary of
    filter names and filter values."""

    filters = {'inactive': 0}
    excludes = {}
    ranges = {}
    metas = {}

    # Status filtering
    if 'status' in kwargs:
        filters['addon_status'] = kwargs['status']

    # We should always have an 'app' except for the admin.
    if 'app' in kwargs:
        # We add SEARCH_ENGINE_APP since search engines work on all apps.
        filters['app'] = (kwargs['app'], SEARCH_ENGINE_APP, )

    (term, platform) = extract_from_query(term, 'platform', '\w+', kwargs)

    if platform:
        if not isinstance(platform, int):
            platform = amo.PLATFORM_DICT.get(platform)
            if platform:
                platform = platform.id
        if platform:
            filters['platform'] = (platform, amo.PLATFORM_ALL.id,)

    # Locale filtering
    if 'locale' in kwargs:
        filters['locale_ord'] = crc32(kwargs['locale'])

    # Xenophobia - restrict to just my language.
    if 'xenophobia' in kwargs and 'admin' not in kwargs:
        filters['locale_ord'] = get_locale_ord()

    # Unless we're in admin mode, or we're looking at stub entries,
    # everything must have a file.
    if (('admin' not in kwargs) and
        ('type' not in kwargs or kwargs['type'] != amo.ADDON_PERSONA)):
        excludes['num_files'] = 0

    # STATUS_DISABLED and 0 (which likely means null) are filtered
    excludes['addon_status'] = (0, amo.STATUS_DISABLED,)

    if 'before' in kwargs:
        ranges['modified'] = (kwargs['before'], THE_FUTURE)

    (term, addon_type) = extract_from_query(term, 'type', '\w+', kwargs)

    if addon_type:
        if not isinstance(addon_type, int):
            types = dict((name.lower(), id) for id, name
                         in amo.ADDON_TYPE.items())
            addon_type = types.get(addon_type.lower())

        metas['type'] = addon_type

    # Category filtering.
    (term, category) = extract_from_query(term, 'category', '\w+', kwargs)

    if category and 'app' in kwargs:
        if not isinstance(category, int):
            category = get_category_id(category, kwargs['app'])

        metas['category'] = category

    (term, tag) = extract_from_query(term, 'tag', '\w+', kwargs)

    if tag:
        tag = Tag.objects.filter(tag_text=tag)[:1]
        if tag:
            metas['tag'] = tag[0].id
        else:
            metas['tag'] = -1

    # TODO:
    # In the interest of having working code sooner than later, we're
    # skipping the following... for now:
    #   * GUID filter
    #   * Num apps filter

    return (term, filters, excludes, ranges, metas)


def get_locale_ord():
    return crc32(settings.LANGUAGE_URL_MAP.get(translation.get_language())
                 or translation.get_language())


class ResultSet(object):
    """
    ResultSet wraps around a query set and provides meta data used for
    pagination.
    """
    def __init__(self, queryset, total, offset):
        self.queryset = queryset
        self.total = total
        self.offset = offset

    def __len__(self):
        return self.total

    def __iter__(self):
        return iter(self.queryset)

    def __getitem__(self, k):
        """`queryset` doesn't contain all `total` items, just the items for the
        current page, so we need to adjust `k`"""
        if isinstance(k, slice) and k.start >= self.offset:
            k = slice(k.start - self.offset, k.stop - self.offset)
        elif isinstance(k, int):
            k -= self.offset

        return self.queryset.__getitem__(k)


def get_category_id(category, application):
    """
    Given a string, get the category id associated with it.
    """
    category = Category.objects.filter(
            slug__istartswith=category,
            application=application)[:1]

    if len(category):
        return category[0].id


def sanitize_query(term):
    term = term.strip('^$ ')
    return term


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
        self.sphinx = sphinx.SphinxClient()
        self.sphinx.SetServer(settings.SPHINX_HOST, settings.SPHINX_PORT)

        self.weight_field = ("@weight + IF(addon_status=%d, 30, 0) + "
                             "IF(locale_ord=%d, 29, 0) AS weight" %
                             (amo.STATUS_PUBLIC, get_locale_ord()))

        # Store meta data about our queries:
        self.meta = {}
        self.queries = {}
        self.query_index = 0
        self.meta_filters = {}

        # TODO(davedash): make this less arbitrary
        # Unique ID used for logging
        self.id = int(random.random() * 10**5)

    def log_query(self, term=None):
        """
        Logs whatever relevant data we can from sphinx.
        """
        filter_msg = []

        for f in self.sphinx._filters:
            msg = '+' if not f['exclude'] else '-'
            msg += '%s: ' % f['attr']

            if 'values' in f:
                msg += '%s' % (f['values'],)
            if 'max' in f and 'min' in f:
                msg += '%d..%d' % (f['min'], f['max'],)

            filter_msg.append(msg)

        debug = lambda x: log.debug('%d %s' % (self.id, x))

        debug(u'Term: %s' % smart_unicode(term))
        debug('Filters: ' + ' '.join(filter_msg))
        debug('Sort: %s' % self.sphinx._sortby)
        debug('Limit: %d' % self.sphinx._limit)
        debug('Offset: %d' % self.sphinx._offset)

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

    def add_meta_query(self, field, term):
        """Adds a 'meta' query to the client, this is an aggregate of some
        field that we can use to populate filters.

        This also adds meta filters that do not match the current query.

        E.g. if we can add back category filters to see what tags exist in
        that data set.
        """

        # We only need to select a single field for aggregate queries.
        self.sphinx.SetSelect(field)
        self.sphinx.SetGroupBy(field, sphinx.SPH_GROUPBY_ATTR)

        # We are adding back all the other meta filters.  This way we can find
        # out all of the possible values of this particular field after we
        # filter down the search.
        filters = self.apply_meta_filters(exclude=field)
        self.sphinx.AddQuery(term, 'addons')

        # We roll back our client and store a pointer to this filter.
        self.remove_filters(len(filters))
        self.queries[field] = self.query_index
        self.query_index += 1
        self.sphinx.ResetGroupBy()

    def apply_meta_filters(self, exclude=None):
        """Apply any meta filters, excluding the filter listed in `exclude`."""

        filters = [f for field, f in self.meta_filters.iteritems()
                   if field != exclude]
        self.sphinx._filters.extend(filters)
        return filters

    def remove_filters(self, num):
        """Remove the `num` last filters from the sphinx query."""
        if num:
            self.sphinx._filters = self.sphinx._filters[:-num]

    def add_filter(self, field, values, meta=False, exclude=False):
        """
        Filters the current sphinx query.  `meta` means we can save pull this
        filter out for meta queries.
        """
        if values is None:
            return

        if not isinstance(values, (tuple, list)):
            values = (values,)

        self.sphinx.SetFilter(field, values, exclude)

        if meta:
            self.meta_filters[field] = self.sphinx._filters.pop()


    def query(self, term, limit=10, offset=0, **kwargs):
        """
        Queries sphinx for a term, and parses specific options.

        The following kwargs will do things:

        limit: limits the number of results.
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
        fields = ("addon_id, app, category, %s" % self.weight_field)

        sc.SetSelect(fields)
        sc.SetFieldWeights({'name': 4})

        # Extract and apply various filters.
        (term, includes, excludes, ranges, metas) = extract_filters(
                term, kwargs)

        for filter, value in includes.iteritems():
            self.add_filter(filter, value)

        for filter, value in excludes.iteritems():
            self.add_filter(filter, value, exclude=True)

        for filter, value in ranges.iteritems():
            self.sphinx.SetFilterRange(filter, value[0], value[1])

        for filter, value in metas.iteritems():
            self.add_filter(filter, value, meta=True)

        # Meta queries serve aggregate data we might want.  Such as filters
        # that the end-user may want to apply to their query.
        if 'meta' in kwargs:
            sc.SetLimits(0, 10000)

            if 'versions' in kwargs['meta']:
                self.add_meta_query('max_ver', term)
                self.add_meta_query('min_ver', term)

            if 'categories' in kwargs['meta']:
                self.add_meta_query('category', term)

            if 'tags' in kwargs['meta']:
                sc.SetFilterRange('tag', 0, BIG_INTEGER)
                self.add_filter('locale_ord', get_locale_ord())
                self.add_meta_query('tag', term)
                self.remove_filters(2)

        sc.SetSelect(fields)

        self.apply_meta_filters()

        # Version filtering.
        (term, version) = extract_from_query(term, 'version', '[0-9.]+',
                                             kwargs)

        if version:
            self.restrict_version(version)

        sort_field = 'weight DESC'

        sort_choices = {
                'newest': 'created DESC',
                'updated': 'modified DESC',
                'name': 'name_ord ASC',
                'rating': 'averagerating DESC',
                'averagerating': 'averagerating DESC',
                'popularity': 'weeklydownloads DESC',
                'weeklydownloads': 'weeklydownloads DESC',
                }

        if 'sort' in kwargs and kwargs['sort']:
            sort_field = sort_choices.get(kwargs.get('sort'))
            if not sort_field:
                log.error("Invalid sort option: %s" % kwargs.get('sort'))
                raise SearchError("Invalid sort option given: %s" %
                                  kwargs.get('sort'))

        sc.SetSortMode(sphinx.SPH_SORT_EXTENDED, sort_field)

        sc.SetGroupBy('addon_id', sphinx.SPH_GROUPBY_ATTR, sort_field)

        sc.SetLimits(min(offset, SPHINX_HARD_LIMIT - 1), limit)

        term = sanitize_query(term)

        sc.AddQuery(term, 'addons')
        self.queries['primary'] = self.query_index
        self.query_index += 1

        self.log_query(term)

        try:
            results = sc.RunQueries()
        except socket.timeout:
            log.error("Query has timed out.")
            raise SearchError("Query has timed out.")
        except Exception, e:
            log.error("Sphinx threw an unknown exception: %s" % e)
            raise SearchError("Sphinx threw an unknown exception.")

        if sc.GetLastError():
            raise SearchError(sc.GetLastError())

        # Handle any meta data we have.
        if 'meta' in kwargs:
            if 'versions' in kwargs['meta']:
                # We don't care about the first 10 digits, since
                # those deal with alpha/preview/etc
                result = results[self.queries['min_ver']]

                # We want to lob off the last 10 digits of a number
                truncate = lambda x: (x / 10 ** 10) * 10 ** 10

                min_vers = [truncate(m['attrs']['min_ver'])
                            for m in result['matches']]
                result = results[self.queries['max_ver']]
                max_vers = [truncate(m['attrs']['max_ver'])
                            for m in result['matches']]
                versions = list(set(min_vers + max_vers))
                sorted(versions, reverse=True)
                self.meta['versions'] = [v for v in versions
                                         if v not in (0, 10 ** 13)]

            if 'categories' in kwargs['meta']:
                result = results[self.queries['category']]
                category_ids = []

                for m in result['matches']:
                    category_ids.extend(m['attrs']['category'])

                category_ids = set(category_ids)
                categories = []

                if category_ids:

                    qs = Category.objects.filter(id__in=set(category_ids))

                    if 'app' in kwargs:
                        qs = qs.filter(application=kwargs['app'])

                    categories = order_by_translation(qs, 'name')

                self.meta['categories'] = categories

            if 'tags' in kwargs['meta']:
                result = results[self.queries['tag']]
                tag_dict = defaultdict(int)

                for m in result['matches']:
                    for tag_id in m['attrs']['tag']:
                        tag_dict[tag_id] += 1
                tag_dict_sorted = sorted(tag_dict.iteritems(),
                        key=lambda x: x[1], reverse=True)[:MAX_TAGS]
                tag_ids = [k for k, v in tag_dict_sorted]
                self.meta['tags'] = manual_order(Tag.objects.all(), tag_ids)

        result = results[self.queries['primary']]
        self.total_found = result['total_found'] if result else 0

        if result and result['total']:
            # Remove transformations for now so we can pull them in later.
            qs = Addon.objects.all()
            transforms = qs._transform_fns
            qs._transform_fns = []

            # Return results as a list of add-ons.
            addon_ids = [m['attrs']['addon_id'] for m in result['matches']]
            addons = []
            for addon_id in addon_ids:
                try:
                    addons.append(qs.get(pk=addon_id))
                except Addon.DoesNotExist:
                    log.warn(u'%d: Result for %s refers to non-existent '
                             'addon: %d' % (self.id, term, addon_id))

            # Do the transforms now that we have all the add-ons.
            for fn in transforms:
                fn(addons)

            return ResultSet(addons, min(self.total_found, SPHINX_HARD_LIMIT),
                             offset)
        else:
            return []
