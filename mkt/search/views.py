from django.shortcuts import redirect

import jingo
from tower import ugettext as _

import amo
import amo.utils
from amo.decorators import json_view
from apps.addons.models import Category
from apps.search.views import WebappSuggestionsAjax, _get_locale_analyzer

import mkt
from mkt.constants import regions
from mkt.regions import get_region
from mkt.webapps.models import Webapp

from . import forms


class FacetLink(object):

    def __init__(self, text, urlparams, selected=False, children=None):
        self.text = text
        self.urlparams = urlparams
        self.selected = selected
        self.children = children or []
        self.null_urlparams = dict((x, None) for x in urlparams)
        self.null_urlparams['page'] = None


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

    rules = {'text': {'query': q, 'boost': 3, 'analyzer': 'standard'},
             'text': {'query': q, 'boost': 4, 'type': 'phrase'},
             'fuzzy': {'value': q, 'boost': 2, 'prefix_length': 4},
             'startswith': {'value': q, 'boost': 1.5}}
    for k, v in rules.iteritems():
        for field in ('name', 'app_slug', 'authors'):
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
        # TODO: Remove summary when bug 862603 lands.
        'summary__text': {'query': q, 'boost': 0.3, 'type': 'phrase'},
    }

    analyzer = _get_locale_analyzer()
    if analyzer:
        more['description_%s__text' % analyzer] = {
            'query': q, 'boost': 0.6, 'type': 'phrase', 'analyzer': analyzer}
        # TODO: Remove summary when bug 862603 lands.
        more['summary_%s__text' % analyzer] = {
            'query': q, 'boost': 0.1, 'type': 'phrase', 'analyzer': analyzer}

    return dict(more, **name_only_query(q))


def _filter_search(request, qs, query, filters=None, sorting=None,
                   sorting_default='-popularity', region=None):
    """Filter an ES queryset based on a list of filters."""
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
            qs = qs.filter(premium_type__in=query.get('premium_types'))
    if 'app_type' in query and query['app_type']:
        qs = qs.filter(app_type=query['app_type'])
    if 'sort' in show:
        sort_by = None
        if query['sort'] in sorting:
            sort_by = sorting[query['sort']]

        # For "Adolescent" regions popularity is global installs + reviews.

        if query['sort'] == 'popularity' and region and not region.adolescent:
            # For "Mature" regions popularity becomes installs + reviews
            # from only that region.
            sort_by = '-popularity_%s' % region.id

        if sort_by:
            qs = qs.order_by(sort_by)
    elif not query.get('q'):

        if (sorting_default == 'popularity' and region and
            not region.adolescent):
            # For "Mature" regions popularity becomes installs + reviews
            # from only that region.
            sorting_default = '-popularity_%s' % region.id

        # Sort by a default if there was no query so results are predictable.
        qs = qs.order_by(sorting_default)

    region = regions.REGIONS_DICT[get_region()]
    # If the region only supports carrier billing for app purchase,
    # don't list apps that require carrier billing to buy.
    if not region.supports_carrier_billing:
        qs = qs.filter(carrier_billing_only=False)
    return qs


def category_sidebar(query, categories):
    qcat = query.get('cat')

    categories = sorted(categories, key=lambda x: x.name)
    cat_params = dict(cat=None)

    rv = [FacetLink(_(u'Any Category'), cat_params, selected=not qcat)]
    rv += [FacetLink(c.name, dict(cat_params, **dict(cat=c.id)),
                     c.id == qcat) for c in categories]
    return rv


def price_sidebar(query):
    qprice = query.get('price')
    free = qprice == 'free'
    paid = qprice == 'paid'
    return [
        FacetLink(_('All'), dict(price=None), not (paid or free)),
        FacetLink(_('Free'), dict(price='free'), free),
        FacetLink(_('Paid'), dict(price='paid'), paid),
    ]


def device_sidebar(query):
    device = query.get('device') or None
    links = []
    for key, label in forms.DEVICE_CHOICES:
        links.append(FacetLink(label, dict(device=key), device == key))
    return links


def sort_sidebar(query, form):
    sort = query.get('sort')
    return [FacetLink(text, dict(sort=key), key == sort)
            for key, text in form.fields['sort'].choices]


def _get_query(region, gaia, mobile, tablet, filters=None, new_idx=False):
    return Webapp.from_search(
        region=region, gaia=gaia, mobile=mobile, tablet=tablet,
        filter_overrides=filters, new_idx=new_idx).facet('category')


def _app_search(request, category=None, browse=None):
    form = forms.AppSearchForm(request.GET, request=request)
    form.is_valid()  # Let the form try to clean data.
    query = form.cleaned_data

    # Remove `sort=price` if `price=free`.
    if query.get('price') == 'free' and query.get('sort') == 'price':
        return {'redirect': amo.utils.urlparams(request.get_full_path(),
                                                sort='popularity',
                                                price='free')}

    region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)

    qs = _get_query(region, gaia=request.GAIA, mobile=request.MOBILE,
                    tablet=request.TABLET)

    qs = _filter_search(request, qs, dict(query), region=region)

    # If we're mobile, leave no witnesses. (i.e.: hide "Applied Filters:
    # Mobile")
    if request.MOBILE and not request.TABLET:
        del query['device']

    pager = amo.utils.paginate(request, qs)
    facets = pager.object_list.facet_counts()

    if category or browse:
        if query.get('price') == 'free':
            sort_opts = forms.FREE_LISTING_SORT_CHOICES
        else:
            sort_opts = forms.LISTING_SORT_CHOICES
    else:
        if query.get('price') == 'free':
            # Remove 'Sort by Price' option if filtering by free apps.
            sort_opts = forms.FREE_SORT_CHOICES
        else:
            sort_opts = form.fields['sort'].choices

    cats = [f['term'] for f in facets['category']]
    categories = Category.objects.filter(type=amo.ADDON_WEBAPP, id__in=cats)

    ctx = {
        'pager': pager,
        'query': query,
        'form': form,
        'sorting': sort_sidebar(query, form),
        'sort_opts': sort_opts,
        'extra_sort_opts': [],
        'sort': query.get('sort'),
        'price': query.get('price'),
        'categories': category_sidebar(query, categories),
        'prices': price_sidebar(query),
        'devices': device_sidebar(query),
        'active': {},
    }

    applied_filters = []
    for facet in ('prices', 'categories', 'devices'):
        for idx, f in enumerate(ctx[facet]):
            # Show filters where something besides its first/default choice
            # is selected.
            if idx and f.selected:
                applied_filters.append(f)
                ctx['active'][facet] = f

    # We shouldn't show the "Applied Filters" for category browse/search pages.
    if not category:
        ctx['applied_filters'] = applied_filters

    return ctx


def app_search(request):
    ctx = _app_search(request)
    category = None

    if 'query' in ctx and 'cat' in ctx['query']:
        cat = ctx['query']['cat']
        cats = Category.objects.filter(type=amo.ADDON_WEBAPP, pk=cat)

        if cats.exists():
            category = cats[0]
    else:
        cat = None

    # If we're supposed to redirect, then do that.
    if ctx.get('redirect'):
        return redirect(ctx['redirect'])

    if category:
        ctx['featured'] = Webapp.featured(cat=category)[:3]

    # Otherwise render results.
    return jingo.render(request, 'search/results.html', ctx)


@json_view
def ajax_search(request):
    category = request.GET.get('category', None) or None
    if category:
        category = int(category)
    return WebappSuggestionsAjax(request, category=category).items
