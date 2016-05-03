from collections import namedtuple

from django.utils import translation

from elasticsearch_dsl import F, query
from elasticsearch_dsl.filter import Bool
from rest_framework.filters import BaseFilterBackend

from olympia import amo


def get_locale_analyzer(lang):
    analyzer = amo.SEARCH_LANGUAGE_TO_ANALYZER.get(lang)
    return analyzer


class SearchQueryFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that performs an ES query according
    so what's in the `q` GET parameter.
    """

    def primary_should_rules(self, search_query, analyzer):
        """Return "primary" should rules for the query.

        These are the ones using the strongest boosts, so they are only applied
        to a specific set of fields like the name, the slug and authors.
        """
        should = []
        rules = [
            (query.Match, {'query': search_query, 'boost': 3,
                           'analyzer': 'standard'}),
            (query.Match, {'query': search_query, 'boost': 4,
                           'type': 'phrase',
                           'slop': 1}),
            (query.Prefix, {'value': search_query, 'boost': 1.5}),
        ]

        # Only add fuzzy queries if the search query is a single word.
        # It doesn't make sense to do a fuzzy query for multi-word queries.
        if ' ' not in search_query:
            rules.append(
                (query.Fuzzy, {'value': search_query, 'boost': 2,
                               'prefix_length': 4}))

        # Apply rules to search on few base fields. Some might not be present
        # in every document type / indexes.
        for k, v in rules:
            for field in ('name', 'slug', 'authors'):
                should.append(k(**{field: v}))

        # For name, also search in translated field with the right language
        # and analyzer.
        if analyzer:
            should.append(
                query.Match(**{'name_%s' % analyzer: {'query': search_query,
                                                      'boost': 2.5,
                                                      'analyzer': analyzer}}))

        return should

    def secondary_should_rules(self, search_query, analyzer):
        """Return "secondary" should rules for the query.

        These are the ones using the weakest boosts, they are applied to fields
        containing more text like description, summary and tags.
        """
        should = [
            query.Match(summary={'query': search_query, 'boost': 0.8,
                                 'type': 'phrase'}),
            query.Match(description={'query': search_query, 'boost': 0.3,
                                     'type': 'phrase'}),
            query.Match(tags={'query': search_query.split(), 'boost': 0.1}),
        ]

        # For description and summary, also search in translated field with the
        # right language and analyzer.
        if analyzer:
            should.extend([
                query.Match(**{'summary_%s' % analyzer: {
                    'query': search_query, 'boost': 0.6, 'type': 'phrase',
                    'analyzer': analyzer}}),
                query.Match(**{'description_%s' % analyzer: {
                    'query': search_query, 'boost': 0.6, 'type': 'phrase',
                    'analyzer': analyzer}})
            ])

        return should

    def filter_queryset(self, request, qs, view):
        search_query = request.GET.get('q', '').lower()

        if not search_query:
            return qs

        lang = translation.get_language()
        analyzer = get_locale_analyzer(lang)

        # Our query consist of a number of should clauses. We call the ones
        # with the higher boost "primary" for convenience.
        primary_should = self.primary_should_rules(search_query, analyzer)
        secondary_should = self.secondary_should_rules(search_query, analyzer)

        # We alter scoring depending on the "boost" field which is defined in
        # the mapping (used to boost public addons higher than the rest).
        functions = [
            query.SF('field_value_factor', field='boost'),
        ]

        # Assemble everything together and return the search "queryset".
        return qs.query('function_score', query=query.Bool(
            should=primary_should + secondary_should), functions=functions)


class SearchParameterFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that filters only items in an ES
    query that match a specific set of fields: app, platform and type.
    """
    # FIXME: add appversion.

    Filter = namedtuple(
        'Filter', ['query_param', 'valid_values', 'reverse', 'es_field'])
    available_filters = [
        Filter(query_param='app', valid_values=amo.APP_IDS,
               reverse=amo.APPS, es_field='app'),
        Filter(query_param='platform', valid_values=amo.PLATFORMS,
               reverse=amo.PLATFORM_DICT, es_field='platforms'),
        Filter(query_param='type', valid_values=amo.ADDON_SEARCH_TYPES,
               reverse=amo.ADDON_SEARCH_SLUGS, es_field='type'),
    ]

    def filter_queryset(self, request, qs, view):
        must = []

        for filter_instance in self.available_filters:
            operator = 'term'
            if filter_instance.query_param in request.GET:
                value = request.GET[filter_instance.query_param]
                try:
                    # Try the int first.
                    value = int(value)
                except ValueError:
                    # Fall back on the string, which needs to be in the reverse
                    # dict.
                    value = filter_instance.reverse.get(value.lower())
                    # If our reverse dict contains objects and not integers,
                    # like for platforms and apps, we need an extra step to
                    # find the integer value.
                    if hasattr(value, 'id'):
                        value = value.id
                if value in filter_instance.valid_values:
                    # Small hack to support the fact that an add-on with
                    # PLATFORM_ALL set supports any platform: when filtering
                    # by any platform, always include PLATFORM_ALL. This means
                    # we need to change the operator to use 'terms' instead of
                    # 'term'.
                    if (filter_instance.query_param == 'platform' and
                            value != amo.PLATFORM_ALL.id):
                        value = [value, amo.PLATFORM_ALL.id]
                        operator = 'terms'
                    must.append(
                        F(operator, **{filter_instance.es_field: value}))

        return qs.filter(Bool(must=must)) if must else qs


class InternalSearchParameterFilter(SearchParameterFilter):
    """Like SearchParameterFilter, but also allows searching by status. Don't
    use in the public search API, should only be available in the internal
    search tool, with the right set of permissions."""
    # FIXME: also allow searching by listed/unlisted, deleted or not,
    # disabled or not.
    available_filters = SearchParameterFilter.available_filters + [
        SearchParameterFilter.Filter(
            query_param='status', valid_values=amo.STATUS_CHOICES_API,
            reverse=amo.STATUS_CHOICES_API_LOOKUP, es_field='status'),
    ]


class PublicContentFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that filters only public items in an
    ES query -- those listed, not deleted, with PUBLIC status and not disabled.
    """
    def filter_queryset(self, request, qs, view):
        return qs.filter(
            Bool(must=[F('term', status=amo.REVIEWED_STATUSES),
                       F('term', has_version=True)],
                 must_not=[F('term', is_deleted=True),
                           F('term', is_listed=False),
                           F('term', is_disabled=True)]))


class SortingFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that applies sorting to an ES query
    according to the request.
    """
    SORTING_PARAMS = {
        'users': '-average_daily_users',
        'rating': '-bayesian_rating',
        'created': '-created',
        'name': 'name_sort',
        'downloads': '-weekly_downloads',
        'updated': '-last_updated',
        'hotness': '-hotness'
    }
    SORTING_DEFAULT = 'downloads'

    def filter_queryset(self, request, qs, view):
        search_query_param = request.GET.get('q')
        sort_param = request.GET.get('sort')
        order_by = None

        if sort_param:
            order_by = [self.SORTING_PARAMS[name] for name in
                        sort_param.split(',') if name in self.SORTING_PARAMS]

        # The default sort behaviour depends on the presence of a query: When
        # querying (with `?q=`) we want to let ES order results by relevance
        # by default. Therefore, if we don't have a valid order_by at this
        # point, only add the default one if we did not have a search query
        # param.
        if not order_by and not search_query_param:
            order_by = [self.SORTING_PARAMS[self.SORTING_DEFAULT]]

        if order_by:
            return qs.sort(*order_by)

        return qs
