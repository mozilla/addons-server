from django.utils import translation
from django.utils.translation import ugettext

import waffle

from elasticsearch_dsl import Q, query
from rest_framework import serializers
from rest_framework.filters import BaseFilterBackend

from olympia import amo
from olympia.addons.indexers import WEBEXTENSIONS_WEIGHT
from olympia.constants.categories import CATEGORIES, CATEGORIES_BY_ID
from olympia.versions.compare import version_int


def get_locale_analyzer(lang):
    analyzer = amo.SEARCH_LANGUAGE_TO_ANALYZER.get(lang)
    return analyzer


class AddonQueryParam(object):
    """Helper to build a simple ES query from a request.GET param."""
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
        if self.is_valid(value):
            return value
        raise ValueError('Invalid "%s" parameter.' % self.query_param)

    def is_valid(self, value):
        return value in self.valid_values

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

    def get_es_query(self):
        return [Q(self.operator, **{self.es_field: self.get_value()})]


class AddonAppQueryParam(AddonQueryParam):
    query_param = 'app'
    reverse_dict = amo.APPS
    valid_values = amo.APP_IDS
    es_field = 'app'

    def get_value_from_reverse_dict(self):
        return self.get_value_from_object_from_reverse_dict()


class AddonAppVersionQueryParam(AddonQueryParam):
    query_param = 'appversion'
    # appversion need special treatment. We need to convert the query parameter
    # into a set of min and max integer values, and filter on those 2 values
    # with the range operator. 'app' parameter also need to be present for it
    # to work.

    def get_values(self):
        appversion = self.request.GET.get(self.query_param)
        app = AddonAppQueryParam(self.request).get_value()

        if appversion and app:
            # Get a min version less than X.0, and a max greater than X.0a
            low = version_int(appversion)
            high = version_int(appversion + 'a')
            if low < version_int('10.0'):
                raise ValueError('Invalid "%s" parameter.' % self.query_param)
            return app, low, high
        raise ValueError(
            'Invalid combination of "%s" and "%s" parameters.' % (
                AddonAppQueryParam.query_param,
                self.query_param))

    def get_es_query(self):
        app_id, low, high = self.get_values()
        return [
            Q('range', **{'current_version.compatible_apps.%d.min' % app_id:
              {'lte': low}}),
            Q('range', **{'current_version.compatible_apps.%d.max' % app_id:
              {'gte': high}}),
        ]


class AddonAuthorQueryParam(AddonQueryParam):
    # Note: this returns add-ons that have at least one matching author
    # when several are provided (separated by a comma).
    # It works differently from the tag filter below that needs all tags
    # provided to match.
    operator = 'terms'
    query_param = 'author'
    es_field = 'listed_authors.username'

    def get_value(self):
        return self.request.GET.get(self.query_param, '').split(',')


class AddonGuidQueryParam(AddonQueryParam):
    # Note: this returns add-ons that match a guid when several are provided
    # (separated by a comma).
    operator = 'terms'
    query_param = 'guid'
    es_field = 'guid'

    def get_value(self):
        value = self.request.GET.get(self.query_param)
        return value.split(',') if value else []


class AddonPlatformQueryParam(AddonQueryParam):
    query_param = 'platform'
    reverse_dict = amo.PLATFORM_DICT
    valid_values = amo.PLATFORMS
    es_field = 'platforms'
    operator = 'terms'  # Because we'll be sending a list every time.

    def get_value(self):
        value = super(AddonPlatformQueryParam, self).get_value()
        # No matter what platform the client wants to see, we always need to
        # include PLATFORM_ALL to match add-ons compatible with all platforms.
        if value != amo.PLATFORM_ALL.id:
            value = [value, amo.PLATFORM_ALL.id]
        else:
            value = [value]
        return value

    def get_value_from_reverse_dict(self):
        return self.get_value_from_object_from_reverse_dict()


class AddonTypeQueryParam(AddonQueryParam):
    query_param = 'type'
    reverse_dict = amo.ADDON_SEARCH_SLUGS
    valid_values = amo.ADDON_SEARCH_TYPES
    es_field = 'type'
    operator = 'terms'

    def get_value(self):
        value = super(AddonTypeQueryParam, self).get_value()
        # if API gets an int rather than string get_value won't return a list.
        return [value] if isinstance(value, int) else value

    def get_value_from_reverse_dict(self):
        values = self.request.GET.get(self.query_param, '').split(',')
        return [self.reverse_dict.get(value.lower()) for value in values]

    def is_valid(self, value):
        if isinstance(value, int):
            return value in self.valid_values
        else:
            return all([_value in self.valid_values for _value in value])


class AddonStatusQueryParam(AddonQueryParam):
    query_param = 'status'
    reverse_dict = amo.STATUS_CHOICES_API_LOOKUP
    valid_values = amo.STATUS_CHOICES_API
    es_field = 'status'


class AddonCategoryQueryParam(AddonQueryParam):
    query_param = 'category'
    es_field = 'category'
    valid_values = CATEGORIES_BY_ID.keys()
    operator = 'terms'

    def __init__(self, request):
        super(AddonCategoryQueryParam, self).__init__(request)
        # Category slugs are only unique for a given type+app combination.
        # Once we have that, it's just a matter of selecting the corresponding
        # dict in the categories constants and use that as the reverse dict,
        # and make sure to use get_value_from_object_from_reverse_dict().
        try:
            app = AddonAppQueryParam(self.request).get_value()
            types = AddonTypeQueryParam(self.request).get_value()
            self.reverse_dict = [CATEGORIES[app][type_] for type_ in types]
        except KeyError:
            raise ValueError(
                'Invalid combination of "%s", "%s" and "%s" parameters.' % (
                    AddonAppQueryParam.query_param,
                    AddonTypeQueryParam.query_param,
                    self.query_param))

    def get_value(self):
        value = super(AddonCategoryQueryParam, self).get_value()
        # if API gets an int rather than string get_value won't return a list.
        return [value] if isinstance(value, int) else value

    def get_value_from_reverse_dict(self):
        return self.get_value_from_object_from_reverse_dict()

    def get_object_from_reverse_dict(self):
        query_value = self.request.GET.get(self.query_param, '').lower()
        values = []
        for reverse_dict in self.reverse_dict:
            value = reverse_dict.get(query_value)
            if value is None:
                raise ValueError('Invalid "%s" parameter.' % self.query_param)
            values.append(value)
        return values

    def get_value_from_object_from_reverse_dict(self):
        return [obj.id for obj in self.get_object_from_reverse_dict()]

    def is_valid(self, value):
        if isinstance(value, int):
            return value in self.valid_values
        else:
            return all([_value in self.valid_values for _value in value])


class AddonTagQueryParam(AddonQueryParam):
    # query_param is needed for SearchParameterFilter below, so we need it
    # even with the custom get_value() implementation.
    query_param = 'tag'

    def get_value(self):
        return self.request.GET.get(self.query_param, '').split(',')

    def get_es_query(self):
        # Just using 'terms' would not work, as it would return any tag match
        # in the list, but we want to exactly match all of them.
        return [Q('term', tags=tag) for tag in self.get_value()]


class AddonExcludeAddonsQueryParam(AddonQueryParam):
    query_param = 'exclude_addons'

    def get_value(self):
        return self.request.GET.get(self.query_param, '').split(',')

    def get_es_query(self):
        filters = []
        values = self.get_value()
        ids = [value for value in values if value.isdigit()]
        slugs = [value for value in values if not value.isdigit()]
        if ids:
            filters.append(Q('ids', values=ids))
        if slugs:
            filters.append(Q('terms', slug=slugs))
        return filters


class AddonFeaturedQueryParam(AddonQueryParam):
    query_param = 'featured'
    reverse_dict = {'true': True}
    valid_values = [True]

    def get_es_query(self):
        self.get_value()  # Call to validate the value - we only want True.
        app_filter = AddonAppQueryParam(self.request)
        app = (app_filter.get_value()
               if self.request.GET.get(app_filter.query_param) else None)
        locale = self.request.GET.get('lang')
        if not app and not locale:
            # If neither app nor locale is specified fall back on is_featured.
            return [Q('term', is_featured=True)]
        queries = []
        if app:
            # Search for featured collections targeting `app`.
            queries.append(
                Q('term', **{'featured_for.application': app}))
        if locale:
            # Search for featured collections targeting `locale` or all locales
            queries.append(
                Q('terms', **{'featured_for.locales': [locale, 'ALL']}))
        return [Q('nested', path='featured_for',
                  query=query.Bool(must=queries))]


class SearchQueryFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that performs an ES query according
    to what's in the `q` GET parameter.
    """
    MAX_QUERY_LENGTH = 100
    MAX_QUERY_LENGTH_FOR_FUZZY_SEARCH = 20

    def primary_should_rules(self, search_query, analyzer):
        """Return "primary" should rules for the query.

        These are the ones using the strongest boosts, so they are only applied
        to a specific set of fields like the name, the slug and authors.

        Applied rules:

        * Prefer phrase matches that allows swapped terms (boost=4)
        * Then text matches, using the standard text analyzer (boost=3)
        * Then text matches, using a language specific analyzer (boost=2.5)
        * Then look for the query as a prefix of a name (boost=1.5)
        """
        should = [
            # Exact matches need to be queried against a non-analyzed field.
            # Let's do a term query on `name.raw` for an exact match against
            # the add-on name and boost it since this is likely what the user
            # wants.
            # Use a super-high boost to avoid `description` or `summary`
            # getting in our way.
            # Put the raw query first to give it a higher priority during
            # Scoring, `boost` alone doesn't necessarily put it first.
            query.Term(**{
                'name.raw': {
                    'value': search_query, 'boost': 100
                }
            })
        ]

        rules = [
            (query.MatchPhrase, {
                'query': search_query, 'boost': 4, 'slop': 1}),
            (query.Match, {
                'query': search_query, 'boost': 3,
                'analyzer': 'standard', 'operator': 'and'}),
            (query.Prefix, {
                'value': search_query, 'boost': 1.5}),
        ]

        # Add a rule for fuzzy matches ("fire bug" => firebug) (boost=2) for
        # short query strings only (long strings, depending on what characters
        # they contain and how many words are present, can be too costly).
        if len(search_query) < self.MAX_QUERY_LENGTH_FOR_FUZZY_SEARCH:
            rules.append((query.Match, {
                'query': search_query, 'boost': 2,
                'prefix_length': 4, 'fuzziness': 'AUTO'}))

        # Apply rules to search on few base fields. Some might not be present
        # in every document type / indexes.
        for query_cls, opts in rules:
            for field in ('name', 'listed_authors.name'):
                should.append(query_cls(**{field: opts}))

        # For name, also search in translated field with the right language
        # and analyzer.
        if analyzer:
            should.append(
                query.Match(**{
                    'name_l10n_%s' % analyzer: {
                        'query': search_query,
                        'boost': 2.5,
                        'analyzer': analyzer,
                        'operator': 'and'
                    }
                })
            )

        return should

    def secondary_should_rules(self, search_query, analyzer):
        """Return "secondary" should rules for the query.

        These are the ones using the weakest boosts, they are applied to fields
        containing more text like description, summary and tags.

        Applied rules:

        * Look for phrase matches inside the summary (boost=0.8)
        * Look for phrase matches inside the summary using language specific
          analyzer (boost=0.6)
        * Look for phrase matches inside the description (boost=0.3).
        * Look for phrase matches inside the description using language
          specific analyzer (boost=0.1).
        * Look for matches inside tags (boost=0.1).
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

    def apply_search_query(self, search_query, qs):
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
            webext_boost_filter = (
                Q('term', **{'current_version.files.is_webextension': True}) |
                Q('term', **{
                    'current_version.files.is_mozilla_signed_extension': True})
            )

            functions.append(
                query.SF({
                    'weight': WEBEXTENSIONS_WEIGHT,
                    'filter': webext_boost_filter
                })
            )

        # Assemble everything together and return the search "queryset".
        return qs.query(
            'function_score',
            query=query.Bool(should=primary_should + secondary_should),
            functions=functions)

    def filter_queryset(self, request, qs, view):
        search_query = request.GET.get('q', '').lower()

        if not search_query:
            return qs

        if len(search_query) > self.MAX_QUERY_LENGTH:
            raise serializers.ValidationError(
                ugettext('Maximum query length exceeded.'))

        return self.apply_search_query(search_query, qs)


class SearchParameterFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend for ES queries that look for items
    matching a specific set of params in request.GET: app, appversion,
    author, category, exclude_addons, platform, tag and type.
    """
    available_filters = [AddonAppQueryParam, AddonAppVersionQueryParam,
                         AddonAuthorQueryParam, AddonCategoryQueryParam,
                         AddonGuidQueryParam, AddonFeaturedQueryParam,
                         AddonPlatformQueryParam, AddonTagQueryParam,
                         AddonTypeQueryParam]

    available_excludes = [AddonExcludeAddonsQueryParam]

    def get_applicable_clauses(self, request, params_to_try):
        clauses = []
        for param_class in params_to_try:
            try:
                # Initialize the param class if its query parameter is
                # present in the request, otherwise don't, to avoid raising
                # exceptions because of missing params in complex filters.
                if param_class.query_param in request.GET:
                    clauses.extend(param_class(request).get_es_query())
            except ValueError as exc:
                raise serializers.ValidationError(*exc.args)
        return clauses

    def filter_queryset(self, request, qs, view):
        bool_kwargs = {}

        must = self.get_applicable_clauses(
            request, self.available_filters)
        must_not = self.get_applicable_clauses(
            request, self.available_excludes)

        if must:
            bool_kwargs['must'] = must

        if must_not:
            bool_kwargs['must_not'] = must_not

        return qs.query(query.Bool(**bool_kwargs)) if bool_kwargs else qs


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
        'name': 'name.raw',
        'random': '_score',
        'rating': '-bayesian_rating',
        'relevance': '_score',
        'updated': '-last_updated',
        'users': '-average_daily_users',
    }

    def filter_queryset(self, request, qs, view):
        search_query_param = request.GET.get('q')
        sort_param = request.GET.get('sort')
        order_by = None

        if sort_param is not None:
            split_sort_params = sort_param.split(',')
            try:
                order_by = [self.SORTING_PARAMS[name] for name in
                            split_sort_params]
            except KeyError:
                raise serializers.ValidationError('Invalid "sort" parameter.')

            # Random sort is a bit special.
            # First, it can't be combined with other sorts.
            if 'random' in split_sort_params and len(split_sort_params) > 1:
                raise serializers.ValidationError(
                    'The "random" "sort" parameter can not be combined.')

            # Second, for perf reasons it's only available when the 'featured'
            # param is present (to limit the number of documents we'll have to
            # apply the random score to) and a search query is absent
            # (to prevent clashing with the score functions coming from a
            # search query).
            if sort_param == 'random':
                is_random_sort_available = (
                    AddonFeaturedQueryParam.query_param in request.GET and
                    not search_query_param
                )
                if is_random_sort_available:
                    qs = qs.query(
                        'function_score', functions=[query.SF('random_score')])
                else:
                    raise serializers.ValidationError(
                        'The "sort" parameter "random" can only be specified '
                        'when the "featured" parameter is also present, and '
                        'the "q" parameter absent.')

        # The default sort depends on the presence of a query: we sort by
        # relevance if we have a query, otherwise by downloads.
        if not order_by:
            sort_param = 'relevance' if search_query_param else 'downloads'
            order_by = [self.SORTING_PARAMS[sort_param]]

        return qs.sort(*order_by)
