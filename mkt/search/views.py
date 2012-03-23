from django.shortcuts import redirect

import jingo
from tower import ugettext as _

import amo
import amo.utils
from apps.addons.models import Category
from apps.search.views import name_query
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


def _filter_search(qs, query, filters, sorting,
                   sorting_default='-weekly_downloads'):
    """Filter an ES queryset based on a list of filters."""
    # Intersection of the form fields present and the filters we want to apply.
    show = [f for f in filters if query.get(f)]

    if query.get('q'):
        qs = qs.query(or_=name_query(query['q']))
    if 'cat' in show:
        qs = qs.filter(category=query['cat'])
    if 'price' in show:
        if query['price'] == 'paid':
            qs = qs.filter(premium_type__in=amo.ADDON_PREMIUMS, price__gt=0)
        elif query['price'] == 'free':
            qs = qs.filter(premium_type=amo.ADDON_FREE, price=0)
    if 'device' in show:
        qs = qs.filter(device=forms.DEVICE_CHOICES_IDS[query['device']])
    if 'sort' in show:
        qs = qs.order_by(sorting[query['sort']])
    elif not query.get('q'):
        # Sort by a default if there was no query so results are predictable.
        qs = qs.order_by(sorting_default)

    return qs


def category_sidebar(query, facets):
    qcat = query.get('cat')
    cats = [f['term'] for f in facets['categories']]
    categories = Category.objects.filter(type=amo.ADDON_WEBAPP, id__in=cats)

    # If category is not listed as a facet, then show All.
    if qcat not in categories.values_list('id', flat=True):
        qcat = None

    categories = sorted(categories, key=lambda x: x.name)
    cat_params = dict(cat=None)

    rv = [FacetLink(_(u'All Apps'), cat_params, selected=not qcat)]
    rv += [FacetLink(c.name, dict(cat_params, **dict(cat=c.id)),
                     c.id == qcat) for c in categories]
    return rv


def price_sidebar(query):
    qprice = query.get('price')
    free = qprice == 'free'
    paid = qprice == 'paid'
    return [
        FacetLink(_('Free & Premium'), dict(price=None), not (paid or free)),
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


def _app_search(request, category=None):
    form = forms.AppSearchForm(request.GET)
    form.is_valid()  # Let the form try to clean data.
    query = form.cleaned_data

    qs = (Webapp.search()
          .filter(type=amo.ADDON_WEBAPP, status=amo.STATUS_PUBLIC,
                  is_disabled=False)
          .facet(categories={'terms': {'field': 'category', 'size': 200}}))

    filters = ['cat', 'price', 'device', 'sort']
    sorting = {'downloads': '-weekly_downloads',
               'rating': '-bayesian_rating',
               'created': '-created',
               'name': 'name_sort',
               'hotness': '-hotness',
               'price': 'price'}
    qs = _filter_search(qs, query, filters, sorting)

    pager = amo.utils.paginate(request, qs)
    facets = pager.object_list.facets

    if category:
        sort_opts = forms.LISTING_SORT_CHOICES
    else:
        if query.get('price') == 'free':
            # Remove 'Sort by Price' option if filtering by free apps.
            sort_opts = forms.FREE_SORT_CHOICES
        else:
            sort_opts = form.fields['sort'].choices

    ctx = {
        'pager': pager,
        'query': query,
        'form': form,
        'sorting': sort_sidebar(query, form),
        'sort_opts': sort_opts,
        'extra_sort_opts': [],
        'sort': query.get('sort'),
        'categories': category_sidebar(query, facets),
        'prices': price_sidebar(query),
        'devices': device_sidebar(query),
        'active': {},
    }

    applied_filters = []
    for facet in ['prices', 'categories', 'devices']:
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
    # Remove `sort=price` if `price=free`.
    data = request.GET
    if data.get('price') == 'free' and data.get('sort') == 'price':
        return redirect(amo.utils.urlparams(request.get_full_path(),
                                            sort=None))

    # Otherwise render results.
    return jingo.render(request, 'search/results.html', _app_search(request))
