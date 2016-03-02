from django.conf import settings
from django.utils import translation

from elasticsearch_dsl import F, query
from elasticsearch_dsl.filter import Bool
from rest_framework.filters import BaseFilterBackend

from olympia import amo


def get_locale_analyzer(lang):
    analyzer = amo.SEARCH_LANGUAGE_TO_ANALYZER.get(lang)
    if not settings.ES_USE_PLUGINS and analyzer in amo.SEARCH_ANALYZER_PLUGINS:
        return None
    return analyzer


class SearchQueryFilter(BaseFilterBackend):
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


class PublicContentFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that filters only public items in an
    ES query -- those listed, not deleted, with PUBLIC status and not disabled.
    """
    def filter_queryset(self, request, qs, view):
        return qs.filter(
            Bool(must=[F('term', status=amo.REVIEWED_STATUSES)],
                 must_not=[F('term', is_deleted=True),
                           F('term', is_listed=False),
                           F('term', is_disabled=True)]))


class SortingFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that applies sorting to an ES query
    according to the request.
    """

    def filter_queryset(self, request, qs, view):
        search_query = request.GET.get('q')

        # When querying (with `?q=`) we want to let ES order results by
        # relevance. Otherwise we order by name (To be tweaked further when
        # we implement ?sort=).
        order_by = None if search_query else ['name_sort']

        if order_by:
            return qs.sort(*order_by)

        return qs
