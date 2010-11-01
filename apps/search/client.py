from collections import defaultdict
import os
import random
import re
import socket

from django.conf import settings
from django.utils import translation
from django.utils.encoding import smart_unicode

import commonware.log
import sphinxapi as sphinx

import amo
from amo.models import manual_order
from addons.models import Addon, Category
from bandwagon.models import Collection
from translations.query import order_by_translation
from tags.models import Tag
from versions.models import AppVersion

from .utils import convert_version, crc32

m_dot_n_re = re.compile(r'^\d+\.\d+$')

# We overload the APP field in sphinx for Search tools and personas
PERSONA_APP = 98
SEARCH_ENGINE_APP = 99
BIG_INTEGER = 10000000    # Used for SetFilterRange
MAX_TAGS = 10             # Number of tags we return by default.
SPHINX_HARD_LIMIT = 1000  # A hard limit that sphinx imposes.
THE_FUTURE = 9999999999
MAX_VERSION = 10 ** 13 - 1  # Large version

log = commonware.log.getLogger('z.sphinx')


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
        filters['app'] = [kwargs['app']]

        # We add personas and search engines if the current app supports them.
        if (amo.APP_IDS.get(kwargs['app']) in
            amo.APP_TYPE_SUPPORT[amo.ADDON_SEARCH]):
            filters['app'].append(SEARCH_ENGINE_APP)

        if (amo.APP_IDS.get(kwargs['app']) in
            amo.APP_TYPE_SUPPORT[amo.ADDON_PERSONA]):
            filters['app'].append(PERSONA_APP)

    (term, platform) = extract_from_query(term, 'platform', '\w+', kwargs)

    if platform:
        if not isinstance(platform, int):
            platform = amo.PLATFORM_DICT.get(platform)
            if platform:
                platform = platform.id
        # If they are seeking out PLATFORM_ALL they mean no platform filtering
        if platform and platform != amo.PLATFORM_ALL.id:
            filters['platform'] = (platform, amo.PLATFORM_ALL.id,)

    # Locale filtering
    if 'locale' in kwargs:
        filters['locale_ord'] = crc32(kwargs['locale'])

    # In order to sort by name we need restrict to just my language.
    if kwargs.get('sort') == 'name':
        filters['locale_ord'] = get_locale_ord()

    # everything must have a file.
    if (('admin' not in kwargs) and
        ('type' not in kwargs or kwargs['type'] != amo.ADDON_PERSONA)):
        excludes['num_files'] = 0

    # STATUS_DISABLED and 0 (which likely means null) are filtered
    excludes['addon_status'] = (amo.STATUS_NULL, amo.STATUS_DISABLED,)

    if settings.SANDBOX_PANIC:
        excludes['addon_status'] = (excludes['addon_status'] +
                                    amo.UNREVIEWED_STATUSES)

    if 'before' in kwargs:
        ranges['modified'] = (kwargs['before'], THE_FUTURE)

    (term, addon_type) = extract_from_query(term, 'type', '\w+', kwargs)

    if addon_type:
        if not isinstance(addon_type, int):
            types = dict((name.lower().split()[0], id) for id, name
                         in amo.ADDON_TYPE.items())
            addon_type = types.get(addon_type.lower())

        metas['type'] = addon_type

    # Guid filtering..
    (term, guids) = extract_from_query(term, 'guid', '[{}@_\.,\-0-9a-zA-Z]+',
                                       end_of_word_boundary=False)

    if guids:
        guids_crc = []

        for guid in guids.split(','):
            if not guid:
                continue
            guids_crc.append(crc32(guid.lower()))

        filters['guid_ord'] = guids_crc

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
    term = term.strip('^$ ').replace('^$', '')
    return term


def extract_from_query(term, filter, regexp, options={},
                       end_of_word_boundary=True):
    """
    This pulls out a keyword filter from a search term and returns the value
    for the filter and a new term with the filter removed.

    E.g. "yslow version:3" will result in (yslow, 3).  Failing this, we'll look
    in the search options dictionary to see if there is a value.
    """
    re_string = r'\b%s:\s*(%s)' % (filter, regexp)

    if end_of_word_boundary:
        re_string += r'\b'

    match = re.search(re_string, term)

    if match:
        term = term.replace(match.group(0), '')
        value = match.group(1)
    else:
        value = options.get(filter, None)
    return (term, value)


class SearchError(Exception):
    pass


class Client(object):
    """A search client that queries sphinx for addons."""

    def __init__(self):
        self.sphinx = sphinx.SphinxClient()

        if os.environ.get('DJANGO_ENVIRONMENT') == 'test':
            self.sphinx.SetServer(settings.SPHINX_HOST,
                                  settings.TEST_SPHINX_PORT)
        else:
            self.sphinx.SetServer(settings.SPHINX_HOST, settings.SPHINX_PORT)

        self.weight_field = ('@weight + IF(addon_status=%d, 3500, 0) + '
                             'IF(locale_ord=%d, 29, 0) + '
                             'sqrt(weeklydownloads) * 0.4 '
                             'AS myweight ' %
                             (amo.STATUS_PUBLIC, get_locale_ord()))

        # Store meta data about our queries:
        self.meta = {}
        self.queries = {}
        self.query_index = 0
        self.meta_filters = {}

        # TODO(davedash): make this less arbitrary
        # Unique ID used for logging
        self.id = int(random.random() * 10 ** 5)

    def get_result_set(self, term, result, offset, limit):
        # Return results as a list of add-ons.
        addon_ids = [m['attrs']['addon_id'] for m in result['matches']]
        log.debug([(m['attrs']['addon_id'], m['attrs'].get('myweight')) for m
                   in result['matches']])
        addons = manual_order(Addon.objects.all(), addon_ids)
        return ResultSet(addons, min(self.total_found, SPHINX_HARD_LIMIT),
                         offset)

    def log_query(self, term=None):
        """Logs whatever relevant data we can from sphinx."""
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
        # upperbound to be ridiculously large.

        if high_int:
            sc.SetFilterRange('max_ver', low_int, MAX_VERSION)
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
        if 'match' in kwargs:
            try:
                sc.SetMatchMode(kwargs['match'])
            except:
                log.error('Invalid match mode: %s' % kwargs['match'])

        # Setup some default parameters for the search.
        fields = ("addon_id, app, category, %s" % self.weight_field)

        sc.SetFieldWeights({'name': 100})

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

        # Sanitize the term before we start adding queries.
        term = sanitize_query(term)

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

        sort_field = 'myweight DESC'

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
                self.meta['versions'] = self._versions_meta(results, **kwargs)
            if 'categories' in kwargs['meta']:
                self.meta['categories'] = self._categories_meta(results,
                                                                **kwargs)
            if 'tags' in kwargs['meta']:
                self.meta['tags'] = self._tags_meta(results, **kwargs)

        result = results[self.queries['primary']]
        self.total_found = result.get('total_found', 0) if result else 0

        if result.get('error'):
            log.warning(result['error'])
            return []  # Fail silently.

        if result and result['total']:
            return self.get_result_set(term, result, offset, limit)
        else:
            return []

    def _versions_meta(self, results, **kwargs):
        # We don't care about the first 10 digits, since
        # those deal with alpha/preview/etc

        # We want to lob off the last 10 digits of a number
        truncate = lambda x: (x / 10 ** 10) * 10 ** 10

        # Acceptable version ranges
        appversions = AppVersion.objects.filter(application=kwargs.get(
            'app', amo.FIREFOX.id))
        acceptable_versions = sorted(set([truncate(a.version_int) for a in
                                          appversions]))

        r = results[self.queries['min_ver']]

        if 'matches' not in r:
            return []

        min_vers = [truncate(m['attrs']['min_ver'])
                    for m in r['matches']]
        r = results[self.queries['max_ver']]

        # 10**13-1 (a bunch of 9s) is a pseudo max_ver that is
        # meaningless for faceted search.
        max_vers = [truncate(m['attrs']['max_ver'])
                    for m in r['matches']]

        version_pairs = zip(min_vers, max_vers)
        versions = []
        for min, max in version_pairs:
            min_idx = 0
            max_idx = len(acceptable_versions)

            if min in acceptable_versions:
                min_idx = acceptable_versions.index(min)

            if max in acceptable_versions:
                max_idx = acceptable_versions.index(max) + 1

            versions.extend(acceptable_versions[min_idx:max_idx])

        return sorted(versions, reverse=True)

    def _categories_meta(self, results, **kwargs):
        r = results[self.queries['category']]

        if 'matches' not in r:
            return []

        category_ids = []
        for m in r['matches']:
            category_ids.extend(m['attrs']['category'])

        category_ids = set(category_ids)
        categories = []

        if category_ids:
            qs = Category.objects.filter(id__in=set(category_ids))
            if 'app' in kwargs:
                qs = qs.filter(application=kwargs['app'])
            categories = order_by_translation(qs, 'name')
        return categories

    def _tags_meta(self, results, **kwargs):
        r = results[self.queries['tag']]
        tag_dict = defaultdict(int)
        if 'matches' not in r:
            return []

        for m in r['matches']:
            for tag_id in m['attrs']['tag']:
                tag_dict[tag_id] += 1
        tag_dict_sorted = sorted(tag_dict.iteritems(),
                key=lambda x: x[1], reverse=True)[:MAX_TAGS]
        tag_ids = [k for k, v in tag_dict_sorted]
        return manual_order(Tag.objects.all(), tag_ids)


class PersonasClient(Client):
    """A search client that queries sphinx for Personas."""

    def query(self, term, limit=10, offset=0, **kwargs):
        sc = self.sphinx
        sc.SetSelect('addon_id')
        sc.SetLimits(min(offset, SPHINX_HARD_LIMIT - 1), limit)
        term = sanitize_query(term)
        self.log_query(term)

        try:
            result = sc.Query(term, 'personas')
        except socket.timeout:
            log.error("Query has timed out.")
            raise SearchError("Query has timed out.")
        except Exception, e:
            log.error("Sphinx threw an unknown exception: %s" % e)
            raise SearchError("Sphinx threw an unknown exception.")

        if sc.GetLastError():
            raise SearchError(sc.GetLastError())

        self.total_found = result['total_found'] if result else 0

        if result and result['total']:
            return self.get_result_set(term, result, offset, limit)
        else:
            return []


class CollectionsClient(Client):
    """A search client that queries sphinx for Collections."""

    def query(self, term, limit=10, offset=0, **kwargs):
        sc = self.sphinx
        weight_field = ('@weight + IF(locale_ord=%d, 29, 0) AS myweight '
                        % get_locale_ord())

        sc.SetSelect('collection_id, %s' % weight_field)
        sc.SetLimits(min(offset, SPHINX_HARD_LIMIT - 1), limit)
        term = sanitize_query(term)

        sort_field = 'weekly_subscribers DESC'

        sort_choices = {
                'weekly': sort_field,
                'monthly': 'monthly_subscribers DESC',
                'all': 'subscribers DESC',
                'rating': 'rating DESC',
                'newest': 'created DESC',
                }

        if 'sort' in kwargs and kwargs['sort']:
            sort_field = sort_choices.get(kwargs.get('sort'))
            if not sort_field:
                log.error("Invalid sort option: %s" % kwargs.get('sort'))
                raise SearchError("Invalid sort option given: %s" %
                                  kwargs.get('sort'))

        sc.SetSortMode(sphinx.SPH_SORT_EXTENDED, 'myweight DESC')
        self.sphinx.SetGroupBy('collection_id', sphinx.SPH_GROUPBY_ATTR,
                               sort_field)

        self.log_query(term)

        try:
            result = sc.Query(term, 'collections')
        except socket.timeout:
            log.error("Query has timed out.")
            raise SearchError("Query has timed out.")
        except Exception, e:
            log.error("Sphinx threw an unknown exception: %s" % e)
            raise SearchError("Sphinx threw an unknown exception.")

        if sc.GetLastError():
            raise SearchError(sc.GetLastError())

        self.total_found = result['total_found'] if result else 0

        if result and result['total']:
            qs = Collection.objects.all()
            transforms = qs._transform_fns
            qs._transform_fns = []

            collection_ids = (m['attrs']['collection_id'] for m
                              in result['matches'])
            collections = []

            for collection_id in collection_ids:
                try:
                    collections.append(qs.get(pk=collection_id))
                except Collection.DoesNotExist:  # pragma: no cover
                    log.warning(u'%d: Result for %s refers to non-existent '
                             'addon: %d' % (self.id, term, collection_id))

            for fn in transforms:
                fn(collections)

            return ResultSet(collections,
                             min(self.total_found, SPHINX_HARD_LIMIT), offset)

        else:
            return []
