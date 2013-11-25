import amo
from apps.search.views import _get_locale_analyzer

from . import forms


DEFAULT_FILTERS = ['cat', 'device', 'premium_types', 'price', 'sort']
DEFAULT_SORTING = {
    'popularity': '-popularity',
    # TODO: Should popularity replace downloads?
    'downloads': '-weekly_downloads',
    'rating': '-bayesian_rating',
    'created': '-created',
    'name': 'name_sort',
    'hotness': '-hotness',
    'price': 'price'
}


def name_only_query(q):
    """
    Returns a dictionary with field/value mappings to pass to elasticsearch.

    This sets up various queries with boosting against the name field in the
    elasticsearch index.

    """
    d = {}

    rules = {
        'term': {'value': q, 'boost': 10},  # Exact match.
        'text': {'query': q, 'boost': 3, 'analyzer': 'standard'},
        'text': {'query': q, 'boost': 4, 'type': 'phrase'},
        'fuzzy': {'value': q, 'boost': 2, 'prefix_length': 4},
        'startswith': {'value': q, 'boost': 1.5}
    }
    for k, v in rules.iteritems():
        for field in ('name', 'app_slug', 'author'):
            d['%s__%s' % (field, k)] = v

    analyzer = _get_locale_analyzer()
    if analyzer:
        d['name_%s__text' % analyzer] = {'query': q, 'boost': 2.5,
                                         'analyzer': analyzer}
    return d


def name_query(q):
    """
    Returns a dictionary with field/value mappings to pass to elasticsearch.

    Note: This is marketplace specific. See apps/search/views.py for AMO.

    """
    more = {
        'description__text': {'query': q, 'boost': 0.8, 'type': 'phrase'},
    }

    analyzer = _get_locale_analyzer()
    if analyzer:
        more['description_%s__text' % analyzer] = {
            'query': q, 'boost': 0.6, 'type': 'phrase', 'analyzer': analyzer}

    more['tags__text'] = {'query': q}

    return dict(more, **name_only_query(q))


def _filter_search(request, qs, query, filters=None, sorting=None,
                   sorting_default='-popularity', region=None, profile=None):
    """
    Filter an ES queryset based on a list of filters.

    If `profile` (a FeatureProfile object) is provided we filter by the
    profile. If you don't want to filter by these don't pass it. I.e. do the
    device detection for when this happens elsewhere.

    """
    # Intersection of the form fields present and the filters we want to apply.
    filters = filters or DEFAULT_FILTERS
    sorting = sorting or DEFAULT_SORTING
    show = filter(query.get, filters)

    if query.get('q'):
        qs = qs.query(should=True, **name_query(query['q'].lower()))
    if 'cat' in show:
        qs = qs.filter(category=query['cat'])
    if 'price' in show:
        if query['price'] == 'paid':
            qs = qs.filter(premium_type__in=amo.ADDON_PREMIUMS)
        elif query['price'] == 'free':
            qs = qs.filter(premium_type__in=amo.ADDON_FREES, price=0)
    if 'device' in show:
        qs = qs.filter(device=forms.DEVICE_CHOICES_IDS[query['device']])
    if 'premium_types' in show:
        if query.get('premium_types'):
            qs = qs.filter(premium_type__in=query['premium_types'])
    if query.get('app_type'):
        qs = qs.filter(app_type__in=query['app_type'])
    if query.get('manifest_url'):
        qs = qs.filter(manifest_url=query['manifest_url'])
    if query.get('offline') is not None:
        qs = qs.filter(is_offline=query.get('offline'))
    if query.get('languages'):
        langs = [x.strip() for x in query['languages'].split(',')]
        qs = qs.filter(supported_locales__in=langs)
    if 'sort' in show:
        sort_by = [sorting[name] for name in query['sort'] if name in sorting]

        # For "Adolescent" regions popularity is global installs + reviews.

        if query['sort'] == 'popularity' and region and not region.adolescent:
            # For "Mature" regions popularity becomes installs + reviews
            # from only that region.
            sort_by = ['-popularity_%s' % region.id]

        if sort_by:
            qs = qs.order_by(*sort_by)
    elif not query.get('q'):

        if (sorting_default == 'popularity' and region and
            not region.adolescent):
            # For "Mature" regions popularity becomes installs + reviews
            # from only that region.
            sorting_default = '-popularity_%s' % region.id

        # Sort by a default if there was no query so results are predictable.
        qs = qs.order_by(sorting_default)

    if profile:
        # Exclude apps that require any features we don't support.
        qs = qs.filter(**profile.to_kwargs(prefix='features.has_'))

    return qs
