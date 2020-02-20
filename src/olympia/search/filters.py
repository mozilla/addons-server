from django.utils import translation
from django.utils.encoding import force_text
from django.utils.http import urlsafe_base64_decode
from django.utils.translation import ugettext

import colorgram
from elasticsearch_dsl import Q, query
from rest_framework import serializers
from rest_framework.filters import BaseFilterBackend
from waffle import switch_is_active

from olympia import amo
from olympia.api.utils import is_gate_active
from olympia.constants.categories import CATEGORIES, CATEGORIES_BY_ID
from olympia.discovery.models import DiscoveryItem
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
        raise ValueError(
            ugettext('Invalid "%s" parameter.' % self.query_param)
        )

    def is_valid(self, value):
        return value in self.valid_values

    def get_value_from_reverse_dict(self):
        value = self.request.GET.get(self.query_param, '')
        return self.reverse_dict.get(value.lower())

    def get_object_from_reverse_dict(self):
        value = self.request.GET.get(self.query_param, '')
        value = self.reverse_dict.get(value.lower())
        if value is None:
            raise ValueError(
                ugettext('Invalid "%s" parameter.' % self.query_param)
            )
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
                raise ValueError(
                    ugettext('Invalid "%s" parameter.' % self.query_param)
                )
            return app, low, high
        raise ValueError(ugettext(
            'Invalid combination of "%s" and "%s" parameters.' % (
                AddonAppQueryParam.query_param,
                self.query_param)))

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
        value = self.request.GET.get(self.query_param, '')

        # Hack for Firefox 'return to AMO' feature (which, sadly, does not use
        # a specific API but rather encodes the guid and adds a prefix to it,
        # only in the search API): if the guid param matches this format, and
        # the feature is enabled through a setting, then we decode it and
        # check it against DiscoItems, which contains the list of add-ons
        # susceptible to appear in disco pane, acting as a list of "safe"
        # add-ons we can enable that feature for.
        # We raise ValueError if anything goes wrong, they are eventually
        # turned into 400 responses and this acts as a kill-switch for the
        # feature in Firefox.
        if value.startswith('rta:') and '@' not in value:
            if not switch_is_active('return-to-amo'):
                raise ValueError(
                    ugettext('Return To AMO is currently disabled')
                )
            try:
                # We need to keep force_text on the input because
                # urlsafe_base64_decode requires str from Django 2.2 onwards.
                value = force_text(
                    urlsafe_base64_decode(force_text(value[4:])))
                if not amo.ADDON_GUID_PATTERN.match(value):
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError(
                    ugettext(
                        'Invalid Return To AMO guid (not in base64url format?)'
                    )
                )

            # Unfortunately we have to check against the database here. We only
            # need to check that a DiscoveryItem exists, if somehow the add-on
            # is not public, it will get filtered out later by
            # ReviewedContentFilter.
            if not DiscoveryItem.objects.filter(addon__guid=value).exists():
                raise ValueError(
                    ugettext(
                        'Invalid Return To AMO guid (not a curated add-on)'
                    )
                )

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
            raise ValueError(ugettext(
                'Invalid combination of "%s", "%s" and "%s" parameters.' % (
                    AddonAppQueryParam.query_param,
                    AddonTypeQueryParam.query_param,
                    self.query_param)))

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
                raise ValueError(
                    ugettext('Invalid "%s" parameter.' % self.query_param)
                )
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

    # These tags are tags that used to exist but don't any more, filtering
    # on them would find nothing, so they are ignored.
    ignored = ('jetpack', 'firefox57')

    def get_value(self):
        return self.request.GET.get(self.query_param, '').split(',')

    def get_es_query(self):
        # Just using 'terms' would not work, as it would return any tag match
        # in the list, but we want to exactly match all of them.
        return [Q('term', tags=tag) for tag in self.get_value()
                if tag not in self.ignored]


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
            filters.append(~Q('ids', values=ids))
        if slugs:
            filters.append(~Q('terms', slug=slugs))
        return filters


class AddonFeaturedQueryParam(AddonQueryParam):
    query_param = 'featured'
    reverse_dict = {'true': True}
    valid_values = [True]
    es_field = 'is_recommended'


class AddonRecommendedQueryParam(AddonQueryParam):
    query_param = 'recommended'
    reverse_dict = {'true': True}
    valid_values = [True]
    es_field = 'is_recommended'


class AddonColorQueryParam(AddonQueryParam):
    query_param = 'color'

    def convert_to_hsl(self, hexvalue):
        # The API is receiving color as a hex string. We store colors in HSL
        # as colorgram generates it (which is on a 0 to 255 scale for each
        # component), so some conversion is necessary.
        if len(hexvalue) == 3:
            hexvalue = ''.join(2 * c for c in hexvalue)
        try:
            rgb = tuple(bytearray.fromhex(hexvalue))
        except ValueError:
            rgb = (0, 0, 0)
        return colorgram.colorgram.hsl(*rgb)

    def get_value(self):
        color = self.request.GET.get(self.query_param, '')
        return self.convert_to_hsl(color.upper().lstrip('#'))

    def get_es_query(self):
        # Thresholds for saturation & luminosity that dictate which query to
        # use to determine matching colors.
        LOW_SATURATION = 255 * 2.5 / 100.
        LOW_LUMINOSITY = 255 * 5 / 100.
        HIGH_LUMINOSITY = 255 * 98 / 100.

        hsl = self.get_value()
        if hsl[1] <= LOW_SATURATION:
            # If we're given a color with a very low saturation, the user is
            # searching for a black/white/grey and we need to take saturation
            # and lightness into consideration, but ignore hue.
            clauses = [
                Q('range', **{'colors.s': {
                    'lte': LOW_SATURATION,
                }}),
                Q('range', **{'colors.l': {
                    'gte': max(min(hsl[2] - 64, 255), 0),
                    'lte': max(min(hsl[2] + 64, 255), 0),
                }})
            ]
        elif hsl[2] <= LOW_LUMINOSITY:
            # If we're given a color with a very low luminosity, we're
            # essentially looking for pure black. We can ignore hue and
            # saturation, they don't have enough impact to matter here.
            clauses = [
                Q('range', **{'colors.l': {'lte': LOW_LUMINOSITY}})
            ]
        elif hsl[2] >= HIGH_LUMINOSITY:
            # Same deal for very high luminosity, this is essentially white.
            clauses = [
                Q('range', **{'colors.l': {'gte': HIGH_LUMINOSITY}})
            ]
        else:
            # Otherwise, we want to do the opposite and just try to match the
            # hue with +/- 10%. The idea is to keep the UI simple, presenting
            # the user with a limited set of colors that still allows them to
            # find all themes.
            # Start by excluding low saturation and low/high luminosity that
            # are handled above.
            clauses = [
                Q('range', **{'colors.s': {'gt': LOW_SATURATION}}),
                Q('range', **{'colors.l': {
                    'gt': LOW_LUMINOSITY,
                    'lt': HIGH_LUMINOSITY
                }}),
            ]
            if hsl[0] - 26 < 0 or hsl[0] + 26 > 255:
                # If the hue minus 10% is below 0 or above 255, we need to wrap
                # the value to match the other end of the spectrum (since hue
                # is an angular dimension on a cylinder). However we can't do a
                # single range query with both lte & gte with a modulo, we'd
                # end up with a range that's impossible to match. Instead we
                # need to split into 2 queries and match either with a |.
                clauses.append(
                    Q('range', **{'colors.h': {'gte': (hsl[0] - 26) % 255}}) |
                    Q('range', **{'colors.h': {'lte': (hsl[0] + 26) % 255}})
                )
            else:
                # If we don't have to wrap around then it's simpler, just need
                # a single range query between 2 values.
                clauses.append(
                    Q('range', **{'colors.h': {
                        'gte': hsl[0] - 26,
                        'lte': hsl[0] + 26,
                    }}),
                )

        # In any case, the color we're looking for needs to be present in at
        # least 25% of the image.
        clauses.append(Q('range', **{'colors.ratio': {'gte': 0.25}}))

        return [Q('nested', path='colors', query=query.Bool(filter=clauses))]


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

        These are the ones using the strongest boosts and are only applied to
        the add-on name.

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

        # The rest of the rules are applied to 'name', the field containing the
        # default locale translation only. That field has word delimiter rules
        # to help find matches, lowercase filter, etc, at the expense of any
        # language-specific features.
        should.extend([
            query.MatchPhrase(**{
                'name': {
                    '_name': 'MatchPhrase(name)',
                    'query': search_query, 'boost': 8.0, 'slop': 1,
                },
            }),
            query.Match(**{
                'name': {
                    '_name': 'Match(name)',
                    'analyzer': 'standard',
                    'query': search_query, 'boost': 6.0, 'operator': 'and',
                },
            }),
            query.Prefix(**{
                'name': {
                    '_name': 'Prefix(name)',
                    'value': search_query, 'boost': 3.0
                },
            }),
        ])

        # Add two queries inside a single DisMax rule (avoiding overboosting
        # when an add-on name matches both queries) to support partial & fuzzy
        # matches (both allowing some words in the query to be absent).
        # For short query strings only (long strings, depending on what
        # characters they contain and how many words are present, can be too
        # costly).
        # Again applied to 'name' in the default locale, without the
        # language-specific analysis.
        if len(search_query) < self.MAX_QUERY_LENGTH_FOR_FUZZY_SEARCH:
            should.append(query.DisMax(
                # We only care if one of these matches, so we leave tie_breaker
                # to the default value of 0.0.
                _name='DisMax(FuzzyMatch(name), Match(name.trigrams))',
                boost=4.0,
                queries=[
                    # For the fuzzy query, only slight mispellings should be
                    # corrected, but we allow some of the words to be absent
                    # as well:
                    # 1 or 2 terms: should all be present
                    # 3 terms: 2 should be present
                    # 4 terms or more: 25% can be absent
                    {
                        'match': {
                            'name': {
                                'query': search_query,
                                'prefix_length': 2,
                                'fuzziness': 'AUTO',
                                'minimum_should_match': '2<2 3<-25%'
                            }
                        }
                    },
                    # For the trigrams query, we require at least 66% of the
                    # trigrams to be present.
                    {
                        'match': {
                            'name.trigrams': {
                                'query': search_query,
                                'minimum_should_match': '66%'
                            }
                        }
                    },
                ]
            ))

        return should

    def secondary_should_rules(
            self, search_query, analyzer, rescore_mode=False):
        """Return "secondary" should rules for the query.

        These are the ones using the weakest boosts, they are applied to fields
        containing more text: description & summary.

        Applied rules:

        * Look for matches inside the summary (boost=3.0)
        * Look for matches inside the description (boost=2.0).

        If we're using a supported language, both rules are done through a
        multi_match that considers both the default locale translation
        (using snowball analyzer) and the translation in the current language
        (using language-specific analyzer). If we're not using a supported
        language then only the first part is applied.

        If rescore_mode is True, the match applied are match_phrase queries
        with a slop of 5 instead of a regular match. As those are more
        expensive they are only done in the 'rescore' part of the query.
        """
        if rescore_mode is False:
            query_class = query.Match
            query_kwargs = {
                'operator': 'and',
            }
            query_class_name = 'Match'
            multi_match_kwargs = {
                'operator': 'and',
            }
        else:
            query_class = query.MatchPhrase
            query_kwargs = {
                'slop': 10,
            }
            query_class_name = 'MatchPhrase'
            multi_match_kwargs = {
                'slop': 10,
                'type': 'phrase',
            }

        if analyzer:
            summary_query_name = (
                'MultiMatch(%s(summary),%s(summary_l10n_%s))' % (
                    query_class_name, query_class_name, analyzer))
            description_query_name = (
                'MultiMatch(%s(description),%s(description_l10n_%s))' % (
                    query_class_name, query_class_name, analyzer))
            should = [
                # When *not* doing a rescore, we do regular non-phrase matches
                # with 'operator': 'and' (see query_class/multi_match_kwargs
                # above). This may seem wrong, the ES docs warn against this,
                # but this is exactly what we want here: we want all terms
                # to be present in either of the fields individually, not some
                # in one and some in another.
                query.MultiMatch(
                    _name=summary_query_name,
                    query=search_query,
                    fields=['summary', 'summary_l10n_%s' % analyzer],
                    boost=3.0,
                    **multi_match_kwargs
                ),
                query.MultiMatch(
                    _name=description_query_name,
                    query=search_query,
                    fields=['description', 'description_l10n_%s' % analyzer],
                    boost=2.0,
                    **multi_match_kwargs
                ),
            ]
        else:
            should = [
                query_class(
                    summary=dict(
                        _name='%s(summary)' % query_class_name,
                        query=search_query,
                        boost=3.0,
                        **query_kwargs)),
                query_class(
                    summary=dict(
                        _name='%s(description)' % query_class_name,
                        query=search_query,
                        boost=2.0,
                        **query_kwargs)),
            ]

        return should

    def rescore_rules(self, search_query, analyzer):
        """
        Rules for the rescore part of the query. Currently just more expensive
        version of secondary_search_rules(), doing match_phrase with a slop
        against summary & description, including translated variants if
        possible.
        """
        return self.secondary_should_rules(
            search_query, analyzer, rescore_mode=True)

    def apply_search_query(self, search_query, qs, sort=None):
        lang = translation.get_language()
        analyzer = get_locale_analyzer(lang)

        # Our query consist of a number of should clauses. We call the ones
        # with the higher boost "primary" for convenience.
        primary_should = self.primary_should_rules(search_query, analyzer)
        secondary_should = self.secondary_should_rules(search_query, analyzer)

        # We alter scoring depending on add-on popularity and whether the
        # add-on is reviewed & public & non-experimental, and whether or not
        # it's recommended.
        functions = [
            query.SF(
                'field_value_factor',
                field='average_daily_users',
                modifier='log2p'),
            query.SF({
                'weight': 4.0,
                'filter': (
                    Q('term', is_experimental=False) &
                    Q('terms', status=amo.REVIEWED_STATUSES) &
                    Q('exists', field='current_version') &
                    Q('term', is_disabled=False)
                )
            }),
            query.SF({
                'weight': 5.0,
                'filter': (
                    Q('term', is_recommended=True)
                )
            }),
        ]

        # Assemble everything together
        qs = qs.query(
            'function_score',
            query=query.Bool(should=primary_should + secondary_should),
            functions=functions)

        if sort is None or sort == 'relevance':
            # If we are searching by relevancy, rescore the top 10
            # (window_size below) results per shard with more expensive rules
            # using match_phrase + slop.
            rescore_query = self.rescore_rules(search_query, analyzer)
            qs = qs.extra(rescore={'window_size': 10, 'query': {
                'rescore_query': query.Bool(should=rescore_query).to_dict()}})

        return qs

    def filter_queryset(self, request, qs, view):
        search_query = request.GET.get('q', '').lower()
        sort_param = request.GET.get('sort')

        if not search_query:
            return qs

        if len(search_query) > self.MAX_QUERY_LENGTH:
            raise serializers.ValidationError(
                ugettext('Maximum query length exceeded.')
            )

        return self.apply_search_query(search_query, qs, sort_param)


class SearchParameterFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend for ES queries that look for items
    matching a specific set of params in request.GET: app, appversion,
    author, category, exclude_addons, platform, tag and type.
    """
    available_clauses = [
        AddonAppQueryParam,
        AddonAppVersionQueryParam,
        AddonAuthorQueryParam,
        AddonCategoryQueryParam,
        AddonExcludeAddonsQueryParam,
        AddonFeaturedQueryParam,
        AddonGuidQueryParam,
        AddonPlatformQueryParam,
        AddonRecommendedQueryParam,
        AddonTagQueryParam,
        AddonTypeQueryParam,
        AddonColorQueryParam,
    ]

    def get_applicable_clauses(self, request):
        clauses = []
        for param_class in self.available_clauses:
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
        filters = self.get_applicable_clauses(request)
        qs = qs.query(query.Bool(filter=filters)) if filters else qs
        return qs


class ReviewedContentFilter(BaseFilterBackend):
    """
    A django-rest-framework filter backend that filters only reviewed items in
    an ES query -- those listed, not deleted, with a reviewed status and not
    disabled.
    """
    def filter_queryset(self, request, qs, view):
        return qs.query(query.Bool(filter=[
            Q('terms', status=amo.REVIEWED_STATUSES),
            Q('exists', field='current_version'),
            Q('term', is_disabled=False),
        ]))


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
        'recommended': '-is_recommended',
        'relevance': '_score',
        'updated': '-last_updated',
        'users': '-average_daily_users',
    }

    def get_sort_params(self, request):
        sort = request.GET.get('sort')
        return sort.split(',') if sort else []

    def filter_queryset(self, request, qs, view):
        search_query_param = request.GET.get('q')
        split_sort_params = self.get_sort_params(request)

        if split_sort_params:
            # Random sort is a bit special.
            # First, it can't be combined with other sorts.
            if 'random' in split_sort_params and len(split_sort_params) > 1:
                raise serializers.ValidationError(
                    'The "random" "sort" parameter can not be combined.')

            # Second, for perf reasons it's only available when the 'featured'
            # or 'recommended' param is present (to limit the number of
            # documents we'll have to apply the random score to) and a search
            # query is absent (to prevent clashing with the score functions
            # coming from a search query).
            if split_sort_params == ['random']:

                is_random_sort_available = (
                    (AddonFeaturedQueryParam.query_param in request.GET or
                     AddonRecommendedQueryParam.query_param in request.GET) and
                    not search_query_param
                )
                if is_random_sort_available:
                    qs = qs.query(
                        'function_score', functions=[query.SF('random_score')])
                else:
                    raise serializers.ValidationError(
                        'The "sort" parameter "random" can only be specified '
                        'when the "featured" or "recommended" parameter is '
                        'also present, and the "q" parameter absent.')

            # Sorting by relevance only makes sense with a query string
            if not search_query_param and 'relevance' in split_sort_params:
                split_sort_params = [
                    param for param in split_sort_params if not 'relevance']

            # Having just recommended sort doesn't make any sense, so ignore it
            if split_sort_params == ['recommended']:
                split_sort_params = None
            # relevance already takes into account recommended so ignore it too
            elif ('recommended' in split_sort_params and
                  'relevance' in split_sort_params):
                split_sort_params = [
                    param for param in split_sort_params if not 'recommended']

        if not split_sort_params:
            # The default sort depends on the presence of a query: we sort by
            # relevance if we have a query, otherwise by recommended,downloads.
            split_sort_params = (
                ['relevance'] if search_query_param else
                ['recommended', 'users']
            )

        try:
            order_by = [self.SORTING_PARAMS[name] for name in
                        split_sort_params]
        except KeyError:
            raise serializers.ValidationError('Invalid "sort" parameter.')

        return qs.sort(*order_by)


class AutoCompleteSortFilter(SortingFilter):
    def get_sort_params(self, request):
        if not is_gate_active(request, 'autocomplete-sort-param'):
            return []
        return super().get_sort_params(request)
