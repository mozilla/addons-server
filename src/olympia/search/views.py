from django import http
from django.db.models import Q
from django.db.transaction import non_atomic_requests
from django.utils.encoding import force_bytes
from django.utils.translation import ugettext
from django.views.decorators.vary import vary_on_headers

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon, Category
from olympia.amo.decorators import json_view
from olympia.amo.templatetags.jinja_helpers import locale_url, urlparams
from olympia.amo.utils import render, sorted_groupby
from olympia.browse.views import personas_listing as personas_listing_view
from olympia.versions.compare import dict_from_int, version_dict, version_int

from .forms import ESSearchForm


DEFAULT_NUM_PERSONAS = 21  # Results appear in a grid of 3 personas x 7 rows.

log = olympia.core.logger.getLogger('z.search')


def _personas(request):
    """Handle the request for persona searches."""

    initial = dict(request.GET.items())

    # Ignore these filters since return the same results for Firefox
    # as for Thunderbird, etc.
    initial.update(appver=None, platform=None)

    form = ESSearchForm(initial, type=amo.ADDON_PERSONA)
    form.is_valid()

    qs = Addon.search_public()
    filters = ['sort']
    mapping = {
        'downloads': '-weekly_downloads',
        'users': '-average_daily_users',
        'rating': '-bayesian_rating',
        'created': '-created',
        'name': 'name.raw',
        'updated': '-last_updated',
        'hotness': '-hotness'}
    results = _filter_search(request, qs, form.cleaned_data, filters,
                             sorting=mapping,
                             sorting_default='-average_daily_users',
                             types=[amo.ADDON_PERSONA])

    form_data = form.cleaned_data.get('q', '')

    search_opts = {}
    search_opts['limit'] = form.cleaned_data.get('pp', DEFAULT_NUM_PERSONAS)
    page = form.cleaned_data.get('page') or 1
    search_opts['offset'] = (page - 1) * search_opts['limit']

    pager = amo.utils.paginate(request, results, per_page=search_opts['limit'])
    categories, filter, base, category = personas_listing_view(request)
    context = {
        'pager': pager,
        'form': form,
        'categories': categories,
        'query': form_data,
        'filter': filter,
        'search_placeholder': 'themes'}
    return render(request, 'search/personas.html', context)


class BaseAjaxSearch(object):
    """Generates a list of dictionaries of add-on objects based on
    ID or name matches. Safe to be served to a JSON-friendly view.

    Sample output:
    [
        {
            "id": 1865,
            "name": "Adblock Plus",
            "url": "http://path/to/details/page",
            "icons": {
                "32": "http://path/to/icon-32",
                "64": "http://path/to/icon-64"
            }
        },
        ...
    ]

    """

    def __init__(self, request, excluded_ids=(), ratings=False):
        self.request = request
        self.excluded_ids = excluded_ids
        self.src = getattr(self, 'src', None)
        self.types = getattr(self, 'types', amo.ADDON_TYPES.keys())
        self.limit = 10
        self.key = 'q'  # Name of search field.
        self.ratings = ratings

        # Mapping of JSON key => add-on property.
        default_fields = {
            'id': 'id',
            'name': 'name',
            'url': 'get_url_path',
            'icons': {
                '32': ('get_icon_url', 32),
                '64': ('get_icon_url', 64)
            }
        }
        self.fields = getattr(self, 'fields', default_fields)
        if self.ratings:
            self.fields['rating'] = 'average_rating'

    def queryset(self):
        """Get items based on ID or search by name."""
        results = Addon.objects.none()
        q = self.request.GET.get(self.key)
        if q:
            try:
                pk = int(q)
            except ValueError:
                pk = None
            qs = None
            if pk:
                qs = Addon.objects.public().filter(id=int(q))
            elif len(q) > 2:
                qs = Addon.search_public().filter_query_string(q.lower())
            if qs:
                results = qs.filter(type__in=self.types)
        return results

    def _build_fields(self, item, fields):
        data = {}
        for key, prop in fields.iteritems():
            if isinstance(prop, dict):
                data[key] = self._build_fields(item, prop)
            else:
                # prop is a tuple like: ('method', 'arg1, 'argN').
                if isinstance(prop, tuple):
                    val = getattr(item, prop[0])(*prop[1:])
                else:
                    val = getattr(item, prop, '')
                    if callable(val):
                        val = val()
                data[key] = unicode(val)
        return data

    def build_list(self):
        """Populate a list of dictionaries based on label => property."""
        results = []
        for item in self.queryset()[:self.limit]:
            if item.id in self.excluded_ids:
                continue
            d = self._build_fields(item, self.fields)
            if self.src and 'url' in d:
                d['url'] = urlparams(d['url'], src=self.src)
            results.append(d)
        return results

    @property
    def items(self):
        return self.build_list()


class SearchSuggestionsAjax(BaseAjaxSearch):
    src = 'ss'


class AddonSuggestionsAjax(SearchSuggestionsAjax):
    # No personas.
    types = [amo.ADDON_EXTENSION, amo.ADDON_THEME, amo.ADDON_DICT,
             amo.ADDON_SEARCH, amo.ADDON_LPAPP]


class PersonaSuggestionsAjax(SearchSuggestionsAjax):
    types = [amo.ADDON_PERSONA]


@json_view
@non_atomic_requests
def ajax_search(request):
    """This is currently used only to return add-ons for populating a
    new collection. Themes (formerly Personas) are included by default, so
    this can be used elsewhere.

    """
    search_obj = BaseAjaxSearch(request)
    search_obj.types = amo.ADDON_SEARCH_TYPES
    return search_obj.items


@json_view
@non_atomic_requests
def ajax_search_suggestions(request):
    cat = request.GET.get('cat', 'all')
    suggesterClass = {
        'all': AddonSuggestionsAjax,
        'themes': PersonaSuggestionsAjax,
    }.get(cat, AddonSuggestionsAjax)
    suggester = suggesterClass(request, ratings=False)
    return _build_suggestions(
        request,
        cat,
        suggester)


def _build_suggestions(request, cat, suggester):
    results = []
    q = request.GET.get('q')
    if q and (q.isdigit() or len(q) > 2):
        q_ = q.lower()

        if cat != 'apps':
            # Applications.
            for a in amo.APP_USAGE:
                name_ = unicode(a.pretty).lower()
                word_matches = [w for w in q_.split() if name_ in w]
                if q_ in name_ or word_matches:
                    results.append({
                        'id': a.id,
                        'name': ugettext(u'{0} Add-ons').format(a.pretty),
                        'url': locale_url(a.short),
                        'cls': 'app ' + a.short
                    })

        # Categories.
        cats = Category.objects
        cats = cats.filter(Q(application=request.APP.id) |
                           Q(type=amo.ADDON_SEARCH))
        if cat == 'themes':
            cats = cats.filter(type=amo.ADDON_PERSONA)
        else:
            cats = cats.exclude(type=amo.ADDON_PERSONA)

        for c in cats:
            if not c.name:
                continue
            name_ = unicode(c.name).lower()
            word_matches = [w for w in q_.split() if name_ in w]
            if q_ in name_ or word_matches:
                results.append({
                    'id': c.id,
                    'name': unicode(c.name),
                    'url': c.get_url_path(),
                    'cls': 'cat'
                })

        results += suggester.items

    return results


def _filter_search(request, qs, query, filters, sorting,
                   sorting_default='-weekly_downloads', types=None):
    """Filter an ES queryset based on a list of filters."""
    if types is None:
        types = []
    APP = request.APP
    # Intersection of the form fields present and the filters we want to apply.
    show = [f for f in filters if query.get(f)]

    if query.get('q'):
        qs = qs.filter_query_string(query['q'])
    if 'platform' in show and query['platform'] in amo.PLATFORM_DICT:
        ps = (amo.PLATFORM_DICT[query['platform']].id, amo.PLATFORM_ALL.id)
        # If we've selected "All Systems" don't filter by platform.
        if ps[0] != ps[1]:
            qs = qs.filter(platforms__in=ps)
    if 'appver' in show:
        # Get a min version less than X.0.
        low = version_int(query['appver'])
        # Get a max version greater than X.0a.
        high = version_int(query['appver'] + 'a')
        # Note: when strict compatibility is not enabled on add-ons, we
        # fake the max version we index in compatible_apps.
        qs = qs.filter(**{
            'current_version.compatible_apps.%s.max__gte' % APP.id: high,
            'current_version.compatible_apps.%s.min__lte' % APP.id: low
        })
    if 'atype' in show and query['atype'] in amo.ADDON_TYPES:
        qs = qs.filter(type=query['atype'])
    else:
        qs = qs.filter(type__in=types)
    if 'cat' in show:
        cat = (Category.objects.filter(id=query['cat'])
               .filter(Q(application=APP.id) | Q(type=amo.ADDON_SEARCH)))
        if not cat.exists():
            show.remove('cat')
        if 'cat' in show:
            qs = qs.filter(category=query['cat'])
    if 'tag' in show:
        qs = qs.filter(tags=query['tag'])
    if 'sort' in show:
        qs = qs.order_by(sorting[query['sort']])
    elif not query.get('q'):
        # Sort by a default if there was no query so results are predictable.
        qs = qs.order_by(sorting_default)

    return qs


@vary_on_headers('X-PJAX')
@non_atomic_requests
def search(request, tag_name=None):
    APP = request.APP
    types = (amo.ADDON_EXTENSION, amo.ADDON_THEME, amo.ADDON_DICT,
             amo.ADDON_SEARCH, amo.ADDON_LPAPP)

    category = request.GET.get('cat')

    if category == 'collections':
        extra_params = {'sort': {'newest': 'created'}}
    else:
        extra_params = None

    fixed = fix_search_query(request.GET, extra_params=extra_params)
    if fixed is not request.GET:
        # We generally want a 301, except if it's a "type", because that's only
        # here to support the new frontend, so a permanent redirect could mess
        # things up when the user is going back and forth between the old and
        # new frontend. https://github.com/mozilla/addons-server/issues/6846
        status = 302 if 'type' in request.GET else 301
        return http.HttpResponseRedirect(
            urlparams(request.path, **fixed), status=status)

    facets = request.GET.copy()

    # In order to differentiate between "all versions" and an undefined value,
    # we use "any" instead of "" in the frontend.
    if 'appver' in facets and facets['appver'] == 'any':
        facets['appver'] = ''

    form = ESSearchForm(facets or {})
    form.is_valid()  # Let the form try to clean data.

    form_data = form.cleaned_data
    if tag_name:
        form_data['tag'] = tag_name

    if category == 'themes' or form_data.get('atype') == amo.ADDON_PERSONA:
        return _personas(request)

    sort, extra_sort = split_choices(form.sort_choices, 'created')
    if form_data.get('atype') == amo.ADDON_SEARCH:
        # Search add-ons should not be searched by ADU, so replace 'Users'
        # sort with 'Weekly Downloads'.
        sort, extra_sort = list(sort), list(extra_sort)
        sort[1] = extra_sort[1]
        del extra_sort[1]

    # Perform search, using aggregation so that we can build the facets UI.
    # Note that we don't need to aggregate on platforms, that facet it built
    # from our constants directly, using the current application for this
    # request (request.APP).
    appversion_field = 'current_version.compatible_apps.%s.max' % APP.id
    qs = (Addon.search_public().filter(app=APP.id)
          .aggregate(tags={'terms': {'field': 'tags'}},
                     appversions={'terms': {'field': appversion_field}},
                     categories={'terms': {'field': 'category', 'size': 200}})
          )

    filters = ['atype', 'appver', 'cat', 'sort', 'tag', 'platform']
    mapping = {'users': '-average_daily_users',
               'rating': '-bayesian_rating',
               'created': '-created',
               'name': 'name.raw',
               'downloads': '-weekly_downloads',
               'updated': '-last_updated',
               'hotness': '-hotness'}
    qs = _filter_search(request, qs, form_data, filters, mapping, types=types)

    pager = amo.utils.paginate(request, qs)

    ctx = {
        'is_pjax': request.META.get('HTTP_X_PJAX'),
        'pager': pager,
        'query': form_data,
        'form': form,
        'sort_opts': sort,
        'extra_sort_opts': extra_sort,
        'sorting': sort_sidebar(request, form_data, form),
        'sort': form_data.get('sort'),
    }
    if not ctx['is_pjax']:
        aggregations = pager.object_list.aggregations
        ctx.update({
            'tag': tag_name,
            'categories': category_sidebar(request, form_data, aggregations),
            'platforms': platform_sidebar(request, form_data),
            'versions': version_sidebar(request, form_data, aggregations),
            'tags': tag_sidebar(request, form_data, aggregations),
        })
    return render(request, 'search/results.html', ctx)


class FacetLink(object):

    def __init__(self, text, urlparams, selected=False, children=None):
        self.text = text
        self.urlparams = urlparams
        self.selected = selected
        self.children = children or []


def sort_sidebar(request, form_data, form):
    sort = form_data.get('sort')
    return [FacetLink(text, {'sort': key}, key == sort)
            for key, text in form.sort_choices]


def category_sidebar(request, form_data, aggregations):
    APP = request.APP
    qatype, qcat = form_data.get('atype'), form_data.get('cat')
    cats = [f['key'] for f in aggregations['categories']]
    categories = Category.objects.filter(id__in=cats)
    if qatype in amo.ADDON_TYPES:
        categories = categories.filter(type=qatype)
    # Search categories don't have an application.
    categories = categories.filter(Q(application=APP.id) |
                                   Q(type=amo.ADDON_SEARCH))

    # If category is listed as a facet but type is not, then show All.
    if qcat in cats and not qatype:
        qatype = True

    # If category is not listed as a facet NOR available for this application,
    # then show All.
    if qcat not in categories.values_list('id', flat=True):
        qatype = qcat = None

    categories = [(_atype, sorted(_cats, key=lambda x: x.name))
                  for _atype, _cats in sorted_groupby(categories, 'type')]

    rv = []
    cat_params = {'cat': None}
    all_label = ugettext(u'All Add-ons')

    rv = [FacetLink(all_label, {'atype': None, 'cat': None}, not qatype)]

    for addon_type, cats in categories:
        selected = addon_type == qatype and not qcat

        # Build the linkparams.
        cat_params = cat_params.copy()
        cat_params.update(atype=addon_type)

        link = FacetLink(amo.ADDON_TYPES[addon_type],
                         cat_params, selected)
        link.children = [
            FacetLink(c.name, dict(cat_params, cat=c.id), c.id == qcat)
            for c in cats]
        rv.append(link)
    return rv


def version_sidebar(request, form_data, aggregations):
    appver = ''
    # If appver is in the request, we read it cleaned via form_data.
    if 'appver' in request.GET or form_data.get('appver'):
        appver = form_data.get('appver')

    app = unicode(request.APP.pretty)
    exclude_versions = getattr(request.APP, 'exclude_versions', [])
    # L10n: {0} is an application, such as Firefox. This means "any version of
    # Firefox."
    rv = [FacetLink(
        ugettext(u'Any {0}').format(app), {'appver': 'any'}, not appver)]
    vs = [dict_from_int(f['key']) for f in aggregations['appversions']]

    # Insert the filtered app version even if it's not a facet.
    av_dict = version_dict(appver)

    if av_dict and av_dict not in vs and av_dict['major']:
        vs.append(av_dict)

    # Valid versions must be in the form of `major.minor`.
    vs = set((v['major'], v['minor1'] if v['minor1'] not in (None, 99) else 0)
             for v in vs)
    versions = ['%s.%s' % v for v in sorted(vs, reverse=True)]

    for version, floated in zip(versions, map(float, versions)):
        if (floated not in exclude_versions and
                floated > request.APP.min_display_version):
            rv.append(FacetLink('%s %s' % (app, version), {'appver': version},
                                appver == version))
    return rv


def platform_sidebar(request, form_data):
    qplatform = form_data.get('platform')
    app_platforms = request.APP.platforms.values()
    ALL = app_platforms.pop(0)

    # The default is to show "All Systems."
    selected = amo.PLATFORM_DICT.get(qplatform, ALL)

    if selected != ALL and selected not in app_platforms:
        # Insert the filtered platform even if it's not a facet.
        app_platforms.append(selected)

    # L10n: "All Systems" means show everything regardless of platform.
    rv = [FacetLink(ugettext(u'All Systems'), {'platform': ALL.shortname},
                    selected == ALL)]
    for platform in app_platforms:
        rv.append(FacetLink(platform.name, {'platform': platform.shortname},
                            platform == selected))
    return rv


def tag_sidebar(request, form_data, aggregations):
    qtag = form_data.get('tag')
    tags = [facet['key'] for facet in aggregations['tags']]
    rv = [FacetLink(ugettext(u'All Tags'), {'tag': None}, not qtag)]
    rv += [FacetLink(tag, {'tag': tag}, tag == qtag) for tag in tags]

    if qtag and qtag not in tags:
        rv += [FacetLink(qtag, {'tag': qtag}, True)]
    return rv


def fix_search_query(query, extra_params=None):
    rv = {force_bytes(k): v for k, v in query.items()}
    changed = False
    # Change old keys to new names.
    keys = {
        'lver': 'appver',
        'pid': 'platform',
        'type': 'atype',
    }
    for old, new in keys.items():
        if old in query:
            rv[new] = rv.pop(old)
            changed = True

    # Change old parameter values to new values.
    params = {
        'sort': {
            'newest': 'updated',
            'popularity': 'downloads',
            'weeklydownloads': 'users',
            'averagerating': 'rating',
            'sortby': 'sort',
        },
        'platform': {
            str(p.id): p.shortname
            for p in amo.PLATFORMS.values()
        },
        'atype': {k: str(v) for k, v in amo.ADDON_SEARCH_SLUGS.items()},
    }
    if extra_params:
        params.update(extra_params)
    for key, fixes in params.items():
        if key in rv and rv[key] in fixes:
            rv[key] = fixes[rv[key]]
            changed = True
    return rv if changed else query


def split_choices(choices, split):
    """Split a list of [(key, title)] pairs after key == split."""
    index = [idx for idx, (key, title) in enumerate(choices)
             if key == split]
    if index:
        index = index[0] + 1
        return choices[:index], choices[index:]
    else:
        return choices, []
