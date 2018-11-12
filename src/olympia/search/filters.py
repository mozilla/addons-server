from django.utils import translation
from django.utils.translation import ugettext

from elasticsearch_dsl import Q, query
from rest_framework import serializers
from rest_framework.filters import BaseFilterBackend

from olympia import amo
from olympia.constants.categories import CATEGORIES, CATEGORIES_BY_ID
from olympia.versions.compare import version_int


def get_locale_analyzer(lang):
    """Return analyzer to use for the specified language code, or None."""
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
    query_param = 'author'
    es_field_prefix = 'listed_authors.'

    def get_value(self):
        return self.request.GET.get(self.query_param, '').split(',')

    def get_es_query(self):
        filters = []
        values = self.get_value()
        ids = [value for value in values if value.isdigit()]
        usernames = [value for value in values if not value.isdigit()]
        if ids or usernames:
            filters.append(
                Q('terms', **{self.es_field_prefix + 'id': ids}) |
                Q('terms', **{self.es_field_prefix + 'username': usernames}))
        return filters


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

    def generate_exact_name_match_query(self, search_query, analyzer):
        """
        Return the query used for exact name matching.

        If the name of the add-on is an exact match for the search query, it's
        likely to be what the user wanted to find. To support that, we need to
        do a term query against a non-analyzed field and boost it super high.
        Since we need to support translations, this function has 2 modes:
        - In the first one, used when we are dealing with a language for which
          we know we didn't store a translation in ES (because we don't have an
          analyzer for it), it only executes a term query against `name.raw`.
        - In the second one, we did store a translation in that language...
          potentially. We don't know in advance if there is a translation for
          each add-on! We need to do a query against both `name.raw` and
          `name_l10n_<analyzer>.raw`, applying the boost only once if both
          match. This is where the DisMax comes in, it's what MultiMatch
          would do, except that it works with Term queries.
        """
        if analyzer is None:
            clause = query.Term(**{
                'name.raw': {
                    '_name': 'Term(name.raw)',
                    'value': search_query, 'boost': 100.0
                }
            })
        else:
            query_name = 'DisMax(Term(name.raw), Term(name_l10n_%s.raw))' % (
                analyzer)
            clause = query.DisMax(
                # We only care if one of these matches, so we leave tie_breaker
                # to the default value of 0.0.
                _name=query_name,
                boost=100.0,
                queries=[
                    {'term': {'name.raw': search_query}},
                    {'term': {'name_l10n_%s.raw' % analyzer: search_query}},
                ]
            )
        return clause

    def primary_should_rules(self, search_query, analyzer):
        """Return "primary" should rules for the query.

        These are the ones using the strongest boosts, so they are only applied
        to a specific set of fields: name and author's name(s).

        Applied rules:

        * Exact match on the name, using the right translation if possible
          (boost=100.0)
        * Then text matches, using a language specific analyzer if possible
          (boost=5.0)
        * Phrase matches that allows swapped terms (boost=8.0)
        * Then text matches, using the standard text analyzer (boost=6.0)
        * Then look for the query as a prefix of a name (boost=3.0)
        """
        should = [
            self.generate_exact_name_match_query(search_query, analyzer)
        ]

        # If we are searching with a language that we support, we also try to
        # do a match against the translated field. If not, we'll do a match
        # against the name in default locale below.
        if analyzer:
            should.append(
                query.Match(**{
                    'name_l10n_%s' % analyzer: {
                        '_name': 'Match(name_l10n_%s)' % analyzer,
                        'query': search_query,
                        'boost': 5.0,
                        'analyzer': analyzer,
                        'operator': 'and'
                    }
                })
            )

        # The rest of the rules are applied to the field containing the default
        # locale only. That field has word delimiter rules to help find
        # matches, lowercase filter, etc, at the expense of any
        # language-specific features.
        rules = [
            (query.MatchPhrase, {
                'query': search_query, 'boost': 8.0, 'slop': 1}),
            (query.Match, {
                'query': search_query, 'boost': 6.0,
                'analyzer': 'standard', 'operator': 'and'}),
            (query.Prefix, {
                'value': search_query, 'boost': 3.0}),
        ]

        # Add a rule for fuzzy matches ("fire bug" => firebug) for short query
        # strings only (long strings, depending on what characters they contain
        # and how many words are present, can be too costly).
        # Again, this is applied to the field without the language-specific
        # analysis.
        if len(search_query) < self.MAX_QUERY_LENGTH_FOR_FUZZY_SEARCH:
            rules.append((query.Match, {
                'query': search_query, 'boost': 4.0,
                'prefix_length': 4, 'fuzziness': 'AUTO'}))

        # Apply all the rules we built above to name and listed_authors.name.
        for query_cls, definition in rules:
            for field in ('name', 'listed_authors.name'):
                # Add a _name for debugging (will appear in matched_queries in
                # meta object for each result).
                cls_name = query_cls.__name__
                if definition.get('fuzziness') == 'AUTO':
                    cls_name = 'Fuzzy%s' % cls_name
                opts = {
                    '_name': '%s(%s)' % (cls_name, field),
                }
                opts.update(definition)
                should.append(query_cls(**{field: opts}))

        return should

    def secondary_should_rules(self, search_query, analyzer):
        """Return "secondary" should rules for the query.

        These are the ones using the weakest boosts, they are applied to fields
        containing more text: description & summary.

        Applied rules:

        * Look for phrase matches inside the summary (boost=3.0)
        * Look for phrase matches inside the description (boost=2.0).

        If we're using a supported language, both rules are done through a
        multi_match that considers both the default locale translation
        (using snowball analyzer) and the translation in the current language
        (using language-specific analyzer). If we're not using a supported
        language then only the first part is applied.
        """
        if analyzer:
            summary_query_name = (
                'MultiMatch(MatchPhrase(summary),'
                'MatchPhrase(summary_l10n_%s))' % analyzer)
            description_query_name = (
                'MultiMatch(MatchPhrase(description),'
                'MatchPhrase(description_l10n_%s))' % analyzer)
            should = [
                query.MultiMatch(
                    _name=summary_query_name,
                    query=search_query,
                    type='phrase',
                    fields=['summary', 'summary_l10n_%s' % analyzer],
                    boost=3.0,
                ),
                query.MultiMatch(
                    _name=description_query_name,
                    query=search_query,
                    type='phrase',
                    fields=['description', 'description_l10n_%s' % analyzer],
                    boost=2.0,
                ),
            ]
        else:
            should = [
                query.MatchPhrase(summary={
                    '_name': 'MatchPhrase(summary)',
                    'query': search_query, 'boost': 3.0}),
                query.MatchPhrase(description={
                    '_name': 'MatchPhrase(description)',
                    'query': search_query, 'boost': 2.0}),
            ]

        return should

    def apply_search_query(self, search_query, qs):
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
