from django.shortcuts import redirect

import jingo
from tower import ugettext as _

import amo
import amo.utils
from amo.decorators import json_view
from amo.urlresolvers import reverse
from apps.addons.models import Category
from apps.search.views import name_query, WebappSuggestionsAjax
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


DEFAULT_FILTERS = ['cat', 'price', 'device', 'sort']
DEFAULT_SORTING = {
    'downloads': '-weekly_downloads',
    'rating': '-bayesian_rating',
    'created': '-created',
    'name': 'name_sort',
    'hotness': '-hotness',
    'price': 'price'
}


def _filter_search(qs, query, filters=None, sorting=None,
                   sorting_default='-weekly_downloads'):
    """Filter an ES queryset based on a list of filters."""
    # Intersection of the form fields present and the filters we want to apply.
    filters = filters or DEFAULT_FILTERS
    sorting = sorting or DEFAULT_SORTING
    show = [f for f in filters if query.get(f)]

    if query.get('q'):
        qs = qs.query(or_=name_query(query['q'].lower()))
    if 'cat' in show:
        qs = qs.filter(category=query['cat'])
    if 'price' in show:
        if query['price'] == 'paid':
            qs = qs.filter(premium_type__in=amo.ADDON_PREMIUMS)
        elif query['price'] == 'free':
            qs = qs.filter(premium_type__in=amo.ADDON_FREES, price=0)
    if 'device' in show:
        qs = qs.filter(device=forms.DEVICE_CHOICES_IDS[query['device']])
    if 'sort' in show:
        qs = qs.order_by(sorting[query['sort']])
    elif not query.get('q'):
        # Sort by a default if there was no query so results are predictable.
        qs = qs.order_by(sorting_default)

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
        FacetLink(_('Any Price'), dict(price=None), not (paid or free)),
        FacetLink(_('Free Only'), dict(price='free'), free),
        FacetLink(_('Premium Only'), dict(price='paid'), paid),
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


def _get_query(request, form, query):
    return (Webapp.search()
            .query(type=amo.ADDON_WEBAPP, status=amo.STATUS_PUBLIC,
                   is_disabled=False)
            .facet(categories={'terms': {'field': 'category', 'size': 200}}))


def _app_search(request, category=None, browse=None):
    form = forms.AppSearchForm(request.GET)
    form.is_valid()  # Let the form try to clean data.
    query = form.cleaned_data

    # Remove `sort=price` if `price=free`.
    if query.get('price') == 'free' and query.get('sort') == 'price':
        return {'redirect': amo.utils.urlparams(request.get_full_path(),
                                                sort='downloads',
                                                price='free')}

    qs = _get_query(request, form, query)
    qs = _filter_search(qs, query)

    pager = amo.utils.paginate(request, qs)
    facets = pager.object_list.facets

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

    cats = [f['term'] for f in facets['categories']]
    categories = Category.objects.filter(type=amo.ADDON_WEBAPP, id__in=cats)

    # If category is not listed as a facet, then remove `cat` and redirect.
    if (query.get('cat') and
        query['cat'] not in categories.values_list('id', flat=True)):
        if category:
            return {'redirect': reverse('search.search')}
        else:
            return {'redirect': amo.utils.urlparams(request.get_full_path(),
                                                    cat=None)}

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

    # If we're supposed to redirect, then do that.
    if ctx.get('redirect'):
        return redirect(ctx['redirect'])

    # Otherwise render results.
    return jingo.render(request, 'search/results.html', ctx)


@json_view
def ajax_search(request):
    category = request.GET.get('category', None) or None
    if category:
        category = int(category)
    return WebappSuggestionsAjax(request, category=category).items
