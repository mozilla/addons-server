from django.utils import translation

from elasticsearch_dsl import Q, query
from rest_framework import serializers
from rest_framework.filters import BaseFilterBackend
import waffle

from olympia import amo
from olympia.addons.indexers import WEBEXTENSIONS_WEIGHT
from olympia.constants.categories import CATEGORIES, CATEGORIES_BY_ID
from olympia.versions.compare import version_int


def get_locale_analyzer(lang):
    analyzer = amo.SEARCH_LANGUAGE_TO_ANALYZER.get(lang)
    return analyzer


class AddonFilterParam(object):
    """Helper to build a simple ES lookup query from a request.GET param."""
    operator = 'term'  # ES filter to use when filtering.
    query_param = None
    reverse_dict = None
    valid_values = None
    es_field = None

    def __init__(self, request):
        self.request = request

    def get_value(self):
        value = self.request.GET.get(self.query_param, '')
        try:
            # Try the int first.
            value = int(value)
        except ValueError:
            # Fall back on the string, it should be a key in the reverse dict.
            value = self.get_value_from_reverse_dict()
        if value in self.valid_values:
            return value
        raise ValueError('Invalid "%s" parameter.' % self.query_param)

    def get_value_from_reverse_dict(self):
        value = self.request.GET.get(self.query_param, '')
        return self.reverse_dict.get(value.lower())

    def get_object_from_reverse_dict(self):
        value = self.request.GET.get(self.query_param, '')
        value = self.reverse_dict.get(value.lower())
        if value is None:
            raise ValueError('Invalid "%s" parameter.' % self.query_param)
        return value

    def get_value_from_object_from_reverse_dict(self):
        return self.get_object_from_reverse_dict().id

    def get_es_filter(self):
        return [Q(self.operator, **{self.es_field: self.get_value()})]


class AddonAppFilterParam(AddonFilterParam):
    query_param = 'app'
    reverse_dict = amo.APPS
    valid_values = amo.APP_IDS
    es_field = 'app'

    def get_value_from_reverse_dict(self):
        return self.get_value_from_object_from_reverse_dict()


class AddonAppVersionFilterParam(AddonFilterParam):
    query_param = 'appversion'
    # appversion need special treatment. We need to convert the query parameter
    # into a set of min and max integer values, and filter on those 2 values
    # with the range operator. 'app' parameter also need to be present for it
    # to work.

    def get_values(self):
        appversion = self.request.GET.get(self.query_param)
        app = AddonAppFilterParam(self.request).get_value()

        if appversion and app:
            # Get a min version less than X.0, and a max greater than X.0a
            low = version_int(appversion)
            high = version_int(appversion + 'a')
            if low < version_int('10.0'):
                raise ValueError('Invalid "%s" parameter.' % self.query_param)
            return app, low, high
        raise ValueError(
            'Invalid combination of "%s" and "%s" parameters.' % (
                AddonAppFilterParam.query_param,
                self.query_param))

    def get_es_filter(self):
        app_id, low, high = self.get_values()
        return [
            Q('range', **{'current_version.compatible_apps.%d.min' % app_id:
              {'lte': low}}),
            Q('range', **{'current_version.compatible_apps.%d.max' % app_id:
              {'gte': high}}),
        ]


class AddonAuthorFilterParam(AddonFilterParam):
    query_param = 'author'
    es_field = 'listed_authors.username'

    def get_value(self):
        return self.request.GET.get(self.query_param, '')


class AddonPlatformFilterParam(AddonFilterParam):
    query_param = 'platform'
    reverse_dict = amo.PLATFORM_DICT
    valid_values = amo.PLATFORMS
    es_field = 'platforms'
    operator = 'terms'  # Because we'll be sending a list every time.

    def get_value(self):
        value = super(AddonPlatformFilterParam, self).get_value()
        # No matter what platform the client wants to see, we always need to
        # include PLATFORM_ALL to match add-ons compatible with all platforms.
        if value != amo.PLATFORM_ALL.id:
            value = [value, amo.PLATFORM_ALL.id]
        else:
            value = [value]
        return value

    def get_value_from_reverse_dict(self):
        return self.get_value_from_object_from_reverse_dict()


class AddonTypeFilterParam(AddonFilterParam):
    query_param = 'type'
    reverse_dict = amo.ADDON_SEARCH_SLUGS
    valid_values = amo.ADDON_SEARCH_TYPES
    es_field = 'type'


class AddonStatusFilterParam(AddonFilterParam):
    query_param = 'status'
    reverse_dict = amo.STATUS_CHOICES_API_LOOKUP
    valid_values = amo.STATUS_CHOICES_API
    es_field = 'status'


class AddonCategoryFilterParam(AddonFilterParam):
    query_param = 'category'
    es_field = 'category'
    valid_values = CATEGORIES_BY_ID.keys()

    def __init__(self, request):
        super(AddonCategoryFilterParam, self).__init__(request)
        # Category slugs are only unique for a given type+app combination.
        # Once we have that, it's just a matter of selecting the corresponding
        # dict in the categories constants and use that as the reverse dict,
        # and make sure to use get_value_from_object_from_reverse_dict().
        try:
            app = AddonAppFilterParam(self.request).get_value()
            type_ = AddonTypeFilterParam(self.request).get_value()

            self.reverse_dict = CATEGORIES[app][type_]
        except KeyError:
            raise ValueError(
                'Invalid combination of "%s", "%s" and "%s" parameters.' % (
                    AddonAppFilterParam.query_param,
                    AddonTypeFilterParam.query_param,
                    self.query_param))

    def get_value_from_reverse_dict(self):
        return self.get_value_from_object_from_reverse_dict()


class AddonTagFilterParam(AddonFilterParam):
    # query_param is needed for SearchParameterFilter below, so we need it
    # even with the custom get_value() implementation.
    query_param = 'tag'

    def get_value(self):
        return self.request.GET.get(self.query_param, '').split(',')

    def get_es_filter(self):
        # Just using 'terms' would not work, as it would return any tag match
        # in the list, but we want to exactly match all of them.
        return [Q('term', tags=tag) for tag in self.get_value()]


class SearchQueryFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that performs an ES query according
    to what's in the `q` GET parameter.
    """

    def primary_should_rules(self, search_query, analyzer):
        """Return "primary" should rules for the query.

        These are the ones using the strongest boosts, so they are only applied
        to a specific set of fields like the name, the slug and authors.
        """
        should = []
        rules = [
            (query.Match, {
                'query': search_query, 'boost': 3,
                'analyzer': 'standard'}),
            (query.MatchPhrase, {
                'query': search_query, 'boost': 4,
                'slop': 1}),
            (query.Prefix, {
                'value': search_query, 'boost': 1.5}),
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
            for field in ('name', 'slug', 'listed_authors.name'):
                should.append(k(**{field: v}))

        # For name, also search in translated field with the right language
        # and analyzer.
        if analyzer:
            should.append(
                query.Match(**{
                    'name_l10n_%s' % analyzer: {
                        'query': search_query,
                        'boost': 2.5,
                        'analyzer': analyzer
                    }
                })
            )

        return should

    def secondary_should_rules(self, search_query, analyzer):
        """Return "secondary" should rules for the query.

        These are the ones using the weakest boosts, they are applied to fields
        containing more text like description, summary and tags.
        """
        should = [
            query.MatchPhrase(summary={'query': search_query, 'boost': 0.8}),
            query.MatchPhrase(description={
                'query': search_query, 'boost': 0.3}),
        ]

        # Append a separate 'match' query for every word to boost tag matches
        for tag in search_query.split():
            should.append(query.Match(tags={'query': tag, 'boost': 0.1}))

        # For description and summary, also search in translated field with the
        # right language and analyzer.
        if analyzer:
            should.extend([
                query.MatchPhrase(**{'summary_l10n_%s' % analyzer: {
                    'query': search_query, 'boost': 0.6,
                    'analyzer': analyzer}}),
                query.MatchPhrase(**{'description_l10n_%s' % analyzer: {
                    'query': search_query, 'boost': 0.6,
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
        # the mapping (used to boost public addons higher than the rest) and,
        # if the waffle switch is on, whether or an addon is a webextension.
        functions = [
            query.SF('field_value_factor', field='boost'),
        ]
        if waffle.switch_is_active('boost-webextensions-in-search'):
            functions.append(
                query.SF({
                    'weight': WEBEXTENSIONS_WEIGHT,
                    'filter': Q(
                        'term',
                        **{'current_version.files.is_webextension': True})
                })
            )

        # Assemble everything together and return the search "queryset".
        return qs.query(
            'function_score',
            query=query.Bool(should=primary_should + secondary_should),
            functions=functions)


class SearchParameterFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend for ES queries that look for items
    matching a specific set of fields in request.GET: app, appversion,
    platform, tag and type.
    """
    available_filters = [AddonAppFilterParam, AddonAppVersionFilterParam,
                         AddonPlatformFilterParam, AddonTypeFilterParam,
                         AddonCategoryFilterParam, AddonTagFilterParam,
                         AddonAuthorFilterParam]

    def filter_queryset(self, request, qs, view):
        must = []

        for filter_class in self.available_filters:
            try:
                # Initialize the filter class if its query parameter is present
                # in the request, otherwise don't, to avoid  raising exceptions
                # because of missing params in complex filters.
                if filter_class.query_param in request.GET:
                    filter_ = filter_class(request)
                    must.extend(filter_.get_es_filter())
            except ValueError as exc:
                raise serializers.ValidationError(*exc.args)

        return qs.query(query.Bool(must=must)) if must else qs


class InternalSearchParameterFilter(SearchParameterFilter):
    """Like SearchParameterFilter, but also allows searching by status. Don't
    use in the public search API, should only be available in the internal
    search tool, with the right set of permissions."""
    # FIXME: also allow searching by listed/unlisted, deleted or not,
    # disabled or not.
    available_filters = SearchParameterFilter.available_filters + [
        AddonStatusFilterParam
    ]


class ReviewedContentFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that filters only reviewed items in
    an ES query -- those listed, not deleted, with a reviewed status and not
    disabled.
    """
    def filter_queryset(self, request, qs, view):
        return qs.query(
            query.Bool(
                must=[Q('terms', status=amo.REVIEWED_STATUSES),
                      Q('exists', field='current_version')],
                must_not=[Q('term', is_deleted=True),
                          Q('term', is_disabled=True)]))


class SortingFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that applies sorting to an ES query
    according to the request.
    """
    SORTING_PARAMS = {
        'created': '-created',
        'downloads': '-weekly_downloads',
        'hotness': '-hotness',
        'name': 'name_sort',
        'rating': '-bayesian_rating',
        'relevance': '-_score',
        'updated': '-last_updated',
        'users': '-average_daily_users',
    }

    def filter_queryset(self, request, qs, view):
        search_query_param = request.GET.get('q')
        sort_param = request.GET.get('sort')
        order_by = None

        if sort_param is not None:
            try:
                order_by = [self.SORTING_PARAMS[name] for name in
                            sort_param.split(',')]
            except KeyError:
                raise serializers.ValidationError('Invalid "sort" parameter.')

        # The default sort depends on the presence of a query: we sort by
        # relevance if we have a query, otherwise by downloads.
        if not order_by:
            sort_param = 'relevance' if search_query_param else 'downloads'
            order_by = [self.SORTING_PARAMS[sort_param]]

        return qs.sort(*order_by)
