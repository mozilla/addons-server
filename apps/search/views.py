from collections import defaultdict

from django.db.models import Q
from django.shortcuts import redirect
from django.utils.encoding import smart_str
from django.views.decorators.vary import vary_on_headers
from django.utils import translation

import commonware.log
import jingo
from tower import ugettext as _
from mobility.decorators import mobile_template

import amo
from search import LANGUAGE_TO_ANALYZER
import bandwagon.views
import browse.views
from addons.models import Addon, Category
from amo.decorators import json_view
from amo.helpers import locale_url, urlparams
from amo.utils import MenuItem, sorted_groupby
from versions.compare import dict_from_int, version_int
from webapps.models import Webapp

from . import forms
from .client import SearchError, CollectionsClient, PersonasClient
from .forms import SecondarySearchForm, ESSearchForm

DEFAULT_NUM_RESULTS = 20

log = commonware.log.getLogger('z.search')


def _get_versions(request, versions, version):
    compats = []
    url = request.get_full_path()

    c = MenuItem()
    (c.text, c.url) = (_('All Versions'), urlparams(url, lver=None, page=None))

    if not version or version == 'any':
        c.selected = True

    compats.append(c)
    seen = {}
    exclude = request.APP.__dict__.get('exclude_versions', [])
    versions.sort(reverse=True)

    for v in versions:
        # v is a version_int so we can get the major and minor:
        v = dict_from_int(v)
        if v['minor1'] == 99:
            text = '%s.*' % v['major']
            v_float = float('%s.99' % v['major'])
        else:
            text = '%s.%s' % (v['major'], v['minor1'])
            v_float = float(text)

        if seen.get(text):
            continue

        seen[text] = 1

        if v_float < request.APP.min_display_version or v_float in exclude:
            continue

        c = MenuItem()
        c.text = text
        c.url = urlparams(url, lver=c.text, page=None)

        if c.text == version:
            c.selected = True
        compats.append(c)

    return compats


def _get_categories(request, categories, addon_type=None, category=None):
    items = []
    url = request.get_full_path()

    i = MenuItem()
    (i.text, i.url) = (_('All'), urlparams(url, atype=None, cat=None,
                                           page=None))

    if not addon_type and not category:
        i.selected = True

    items.append(i)

    # Bucket the categories as addon_types so we can display them in a
    # hierarchy.
    bucket = defaultdict(list)

    for cat in categories:
        item = MenuItem()
        (item.text, item.url) = (cat.name, urlparams(url, atype=None,
                page=None, cat="%d,%d" % (cat.type, cat.id)))

        if category == cat.id:
            item.selected = True

        bucket[cat.type].append(item)

    for key in sorted(bucket):
        children = bucket[key]
        item = MenuItem()
        item.children = children
        (item.text, item.url) = (amo.ADDON_TYPES[key],
                                 urlparams(url, atype=key, cat=None,
                                           page=None))
        if not category and addon_type == key:
            item.selected = True

        items.append(item)

    return items


def _get_platforms(request, platforms, selected=None):
    items = []
    url = request.get_full_path()

    if amo.PLATFORM_ALL.id in platforms:
        platforms = amo.PLATFORMS.keys()

    for platform in platforms:
        if platform == amo.PLATFORM_ALL.id:
            continue
        item = MenuItem()
        p = amo.PLATFORMS[platform]
        (item.text, item.url) = (p.name,
                                 urlparams(url, pid=(p.id or None), page=None))
        if p.id == selected:
            item.selected = True
        items.append(item)

    return items


def _get_tags(request, tags, selected):
    items = []
    url = request.get_full_path()

    for tag in tags:
        item = MenuItem()
        (item.text, item.url) = (tag.tag_text.lower(),
                 urlparams(url, tag=tag.tag_text.encode('utf8').lower(),
                           page=None))

        if tag.tag_text.lower() == selected:
            item.selected = True

        items.append(item)

    return items


def _get_sort_menu(request, sort):
    items = []
    sorts = forms.sort_by

    item = (None, _('Keyword Match'))
    items.append(item)

    for key, val in sorts:
        if key == '':
            continue
        item = (key, val)
        items.append(item)

    return items


def _get_sorts(request, sort):
    items = []
    url = request.get_full_path()

    sorts = forms.sort_by

    item = MenuItem()
    (item.text, item.url) = (_('Keyword Match'), urlparams(url, sort=None))

    if not sort:
        item.selected = True

    items.append(item)

    for key, val in sorts:
        if key == '':
            continue

        item = MenuItem()
        (item.text, item.url) = (val, urlparams(url, sort=key, page=None))

        if sort == key:
            item.selected = True

        items.append(item)

    return items


def _personas(request):
    """Handle the request for persona searches."""
    form = SecondarySearchForm(request.GET)
    if not form.is_valid():
        log.error(form.errors)

    query = form.data.get('q', '')

    search_opts = {}
    search_opts['limit'] = form.cleaned_data.get('pp', DEFAULT_NUM_RESULTS)
    page = form.cleaned_data.get('page') or 1
    search_opts['offset'] = (page - 1) * search_opts['limit']

    try:
        results = PersonasClient().query(query, **search_opts)
    except SearchError:
        return jingo.render(request, 'search/down.html', {}, status=503)

    pager = amo.utils.paginate(request, results, search_opts['limit'])
    categories, filter, _, _ = browse.views.personas_listing(request)
    c = dict(pager=pager, form=form, categories=categories, query=query,
             filter=filter)
    return jingo.render(request, 'search/personas.html', c)


def _collections(request):
    """Handle the request for collections."""
    form = SecondarySearchForm(request.GET)
    form.is_valid()

    query = form.cleaned_data.get('q', '')

    search_opts = {}
    search_opts['limit'] = form.cleaned_data.get('pp', DEFAULT_NUM_RESULTS)
    page = form.cleaned_data.get('page') or 1
    search_opts['offset'] = (page - 1) * search_opts['limit']
    search_opts['sort'] = form.cleaned_data.get('sortby')

    try:
        results = CollectionsClient().query(query, **search_opts)
    except SearchError:
        return jingo.render(request, 'search/down.html', {}, status=503)

    pager = amo.utils.paginate(request, results, search_opts['limit'])
    c = dict(pager=pager, form=form, query=query, opts=search_opts,
             filter=bandwagon.views.get_filter(request))
    return jingo.render(request, 'search/collections.html', c)


class BaseAjaxSearch(object):
    """Generates a list of dictionaries of add-on objects based on
    ID or name matches. Safe to be served to a JSON-friendly view.

    Sample output:
    [
        {
            "id": 1865,
            "name": "Adblock Plus",
            "url": "http://path/to/details/page",
            "icon": "http://path/to/icon",
        },
        ...
    ]

    """

    def __init__(self, request, excluded_ids=[]):
        self.request = request
        self.excluded_ids = excluded_ids
        self.src = getattr(self, 'src', None)
        self.types = getattr(self, 'types', amo.ADDON_SEARCH_TYPES)
        self.limit = 10
        self.key = 'q'  # Name of search field.

        # Mapping of JSON key => add-on property.
        default_fields = {
            'id': 'id',
            'name': 'name',
            'url': 'get_url_path',
            'icon': 'icon_url'
        }
        self.fields = getattr(self, 'fields', default_fields)
        self.items = self.build_list()

    def queryset(self):
        """Get items based on ID or search by name."""
        results = []
        if self.key in self.request.GET:
            q = self.request.GET[self.key]
            if q.isdigit() or (not q.isdigit() and len(q) > 2):
                if q.isdigit():
                    qs = Addon.objects.filter(id=int(q),
                                              disabled_by_user=False)
                else:
                    # Oh, how I wish I could elastically exclude terms.
                    qs = (Addon.search().query(or_=name_only_query(q.lower()))
                          .filter(is_disabled=False))
                results = qs.filter(type__in=self.types,
                                    status__in=amo.REVIEWED_STATUSES)
        return results

    def build_list(self):
        """Populate a list of dictionaries based on label => property."""
        results = []
        for item in self.queryset()[:self.limit]:
            if item.id in self.excluded_ids:
                continue
            d = {}
            for key, prop in self.fields.iteritems():
                val = getattr(item, prop, '')
                if callable(val):
                    val = val()
                d[key] = unicode(val)
            if self.src and 'url' in d:
                d['url'] = urlparams(d['url'], src=self.src)
            results.append(d)
        return results


class SearchSuggestionsAjax(BaseAjaxSearch):
    src = 'ss'


class AddonSuggestionsAjax(SearchSuggestionsAjax):
    # No personas. No webapps.
    types = [amo.ADDON_ANY, amo.ADDON_EXTENSION, amo.ADDON_THEME,
             amo.ADDON_DICT, amo.ADDON_SEARCH, amo.ADDON_LPAPP]


class PersonaSuggestionsAjax(SearchSuggestionsAjax):
    types = [amo.ADDON_PERSONA]


class WebappSuggestionsAjax(SearchSuggestionsAjax):
    types = [amo.ADDON_WEBAPP]


@json_view
def ajax_search(request):
    """This is currently used only to return add-ons for populating a
    new collection. Personas are included by default, so this can be
    used elsewhere.

    """
    return BaseAjaxSearch(request).items


@json_view
def ajax_search_suggestions(request):
    results = []
    q = request.GET.get('q')
    if q and (q.isdigit() or (not q.isdigit() and len(q) > 2)):
        q_ = q.lower()

        cat = request.GET.get('cat', 'all')

        # Applications.
        for a in amo.APP_USAGE:
            if q_ in unicode(a.pretty).lower():
                results.append({
                    'id': a.id,
                    'name': _(u'{0} Add-ons').format(a.pretty),
                    'url': locale_url(a.short),
                    'cls': 'app ' + a.short
                })

        # Categories.
        cats = (Category.objects
                .filter(Q(application=request.APP.id) |
                        Q(type=amo.ADDON_SEARCH)))
        if cat == 'personas':
            cats = cats.filter(type=amo.ADDON_PERSONA)
        elif cat == 'apps':
            cats = cats.filter(type=amo.ADDON_WEBAPP)
        else:
            cats = cats.exclude(type__in=[amo.ADDON_PERSONA, amo.ADDON_WEBAPP])

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

        suggestions = {
            'all': AddonSuggestionsAjax,
            'personas': PersonaSuggestionsAjax,
            'apps': WebappSuggestionsAjax,
        }.get(cat, AddonSuggestionsAjax)

        results += suggestions(request).items

    return results


def _get_locale_analyzer():
    return LANGUAGE_TO_ANALYZER.get(translation.get_language())


def name_only_query(q):
    d = dict(name__text={'query': q, 'boost': 3, 'analyzer': 'standard'},
             name__fuzzy={'value': q, 'boost': 2, 'prefix_length': 4},
             name__startswith={'value': q, 'boost': 1.5})

    analyzer = _get_locale_analyzer()
    if analyzer:
        d['name_%s__text' % analyzer] = {'query': q, 'boost': 2.5,
                                         'analyzer': analyzer}
    return d


def name_query(q):
    # * Prefer text matches first, using the standard text analyzer (boost=3).
    # * Then text matches, using language-specific analyzer (boost=2.5).
    # * Then try fuzzy matches ("fire bug" => firebug) (boost=2).
    # * Then look for the query as a prefix of a name (boost=1.5).
    # * Look for phrase matches inside the summary (boost=0.8).
    # * Look for phrase matches inside the summary using language specific
    #   analyzer (boost=0.6).
    # * Look for phrase matches inside the description (boost=0.3).
    # * Look for phrase matches inside the description using language
    #   specific analyzer (boost=0.1).
    more = dict(summary__text={'query': q, 'boost': 0.8, 'type': 'phrase'},
                description__text={'query': q, 'boost': 0.3, 'type': 'phrase'})

    analyzer = _get_locale_analyzer()
    if analyzer:
        more['summary_%s__test' % analyzer] = {'query': q,
                                               'boost': 0.6,
                                               'type': 'phrase',
                                               'analyzer': analyzer}
        more['description_%s__text' % analyzer] = {'query': q,
                                                   'boost': 0.1,
                                                   'type': 'phrase',
                                                   'analyzer': analyzer}
    return dict(more, **name_only_query(q))


@mobile_template('search/{mobile/}results.html')
@vary_on_headers('X-PJAX')
def app_search(request, template=None):
    form = ESSearchForm(request.GET or {}, type=amo.ADDON_WEBAPP)
    form.is_valid()  # Let the form try to clean data.
    query = form.cleaned_data
    qs = (Webapp.search().query(or_=name_query(query['q']))
          .filter(type=amo.ADDON_WEBAPP, status=amo.STATUS_PUBLIC,
                  is_disabled=False)
          .facet(tags={'terms': {'field': 'tag'}},
                 categories={'terms': {'field': 'category', 'size': 100}}))
    if query.get('tag'):
        qs = qs.filter(tag=query['tag'])
    if query.get('cat'):
        qs = qs.filter(category=query['cat'])
    if query.get('sort'):
        mapping = {'downloads': '-weekly_downloads',
                   'rating': '-bayesian_rating',
                   'created': '-created',
                   'name': '-name_sort',
                   'hotness': '-hotness'}
        qs = qs.order_by(mapping[query['sort']])

    pager = amo.utils.paginate(request, qs)
    facets = pager.object_list.facets

    ctx = {
        'is_pjax': request.META.get('HTTP_X_PJAX'),
        'pager': pager,
        'query': query,
        'form': form,
        'sorting': sort_sidebar(request, query, form),
        'sort_opts': form.fields['sort'].choices,
    }
    if not ctx['is_pjax']:
        ctx.update({
            'categories': category_sidebar(request, query, facets),
            'tags': tag_sidebar(request, query, facets),
        })
    return jingo.render(request, template, ctx)


@mobile_template('search/{mobile/}results.html')
@vary_on_headers('X-PJAX')
def search(request, tag_name=None, template=None):
    APP = request.APP
    types = (amo.ADDON_EXTENSION, amo.ADDON_THEME, amo.ADDON_DICT,
             amo.ADDON_SEARCH, amo.ADDON_LPAPP)

    fixed = fix_search_query(request.GET)
    if fixed is not request.GET:
        return redirect(urlparams(request.path, **fixed), permanent=True)

    form = ESSearchForm(request.GET or {})
    form.is_valid()  # Let the form try to clean data.

    category = request.GET.get('cat')
    query = form.cleaned_data

    if category == 'collections':
        return _collections(request)
    elif category == 'personas' or query.get('atype') == amo.ADDON_PERSONA:
        return _personas(request)

    sort, extra_sort = split_choices(form.fields['sort'].choices, 'created')

    qs = (Addon.search()
          .filter(status__in=amo.REVIEWED_STATUSES, is_disabled=False,
                  app=APP.id)
          .facet(tags={'terms': {'field': 'tag'}},
                 platforms={'terms': {'field': 'platform'}},
                 appversions={'terms':
                              {'field': 'appversion.%s.max' % APP.id}},
                 categories={'terms': {'field': 'category', 'size': 100}}))
    if query.get('q'):
        qs = qs.query(or_=name_query(query['q']))
    if tag_name or query.get('tag'):
        qs = qs.filter(tag=tag_name or query['tag'])
    if query.get('platform') and query['platform'] in amo.PLATFORM_DICT:
        ps = (amo.PLATFORM_DICT[query['platform']].id, amo.PLATFORM_ALL.id)
        qs = qs.filter(platform__in=ps)
    if query.get('appver'):
        # Get a min version less than X.0.
        low = version_int(query['appver'])
        # Get a max version greater than X.0a.
        high = version_int(query['appver'] + 'a')
        qs = qs.filter(**{'appversion.%s.max__gte' % APP.id: high,
                          'appversion.%s.min__lte' % APP.id: low})
    if query.get('atype') and query['atype'] in amo.ADDON_TYPES:
        qs = qs.filter(type=query['atype'])
        if query['atype'] == amo.ADDON_SEARCH:
            # Search add-ons should not be searched by ADU, so replace 'Users'
            # sort with 'Weekly Downloads'.
            sort[1] = extra_sort[1]
            del extra_sort[1]
    else:
        qs = qs.filter(type__in=types)
    if query.get('cat'):
        qs = qs.filter(category=query['cat'])
    if query.get('sort'):
        mapping = {'users': '-average_daily_users',
                   'rating': '-bayesian_rating',
                   'created': '-created',
                   'name': 'name_sort',
                   'downloads': '-weekly_downloads',
                   'updated': '-last_updated',
                   'hotness': '-hotness'}
        qs = qs.order_by(mapping[query['sort']])
    elif not query.get('q'):
        # Sort by weekly downloads if there was no query so we get predictable
        # results.
        qs = qs.order_by('-weekly_downloads')

    pager = amo.utils.paginate(request, qs)

    ctx = {
        'is_pjax': request.META.get('HTTP_X_PJAX'),
        'pager': pager,
        'query': query,
        'form': form,
        'sort_opts': sort,
        'extra_sort_opts': extra_sort,
        'sorting': sort_sidebar(request, query, form),
    }
    if not ctx['is_pjax']:
        facets = pager.object_list.facets
        ctx.update({
            'categories': category_sidebar(request, query, facets),
            'platforms': platform_sidebar(request, query, facets),
            'versions': version_sidebar(request, query, facets),
            'tags': tag_sidebar(request, query, facets),
        })
    return jingo.render(request, template, ctx)


class FacetLink(object):

    def __init__(self, text, urlparams, selected=False, children=None):
        self.text = text
        self.urlparams = urlparams
        self.selected = selected
        self.children = children or []


def sort_sidebar(request, query, form):
    sort = query.get('sort')
    return [FacetLink(text, dict(sort=key), key == sort)
            for key, text in form.fields['sort'].choices]


def category_sidebar(request, query, facets):
    APP = request.APP
    qatype, qcat = query.get('atype'), query.get('cat')
    cats = [f['term'] for f in facets['categories']]
    categories = (Category.objects.filter(id__in=cats)
                  # Search categories don't have an application.
                  .filter(Q(application=APP.id) | Q(type=amo.ADDON_SEARCH)))
    if qatype in amo.ADDON_TYPES:
        categories = categories.filter(type=qatype)
    categories = [(atype, sorted(cats, key=lambda x: x.name))
                  for atype, cats in sorted_groupby(categories, 'type')]
    rv = [FacetLink(_(u'All Add-ons'), dict(atype=None, cat=None), not qatype)]
    for addon_type, cats in categories:
        link = FacetLink(amo.ADDON_TYPES[addon_type],
                         dict(atype=addon_type, cat=None),
                         addon_type == qatype and not qcat)
        link.children = [FacetLink(c.name, dict(atype=addon_type, cat=c.id),
                                   c.id == qcat) for c in cats]
        rv.append(link)
    return rv


def version_sidebar(request, query, facets):
    appver = query.get('appver')
    app = unicode(request.APP.pretty)
    exclude_versions = getattr(request.APP, 'exclude_versions', [])
    # L10n: {0} is an application, such as Firefox. This means "any version of
    # Firefox."
    rv = [FacetLink(_(u'Any {0}').format(app), dict(appver=None), not appver)]
    vs = [dict_from_int(f['term']) for f in facets['appversions']]
    vs = set((v['major'], v['minor1'] if v['minor1'] != 99 else 0)
             for v in vs)
    versions = ['%s.%s' % v for v in sorted(vs, reverse=True)]
    for version, floated in zip(versions, map(float, versions)):
        if (floated not in exclude_versions
            and floated > request.APP.min_display_version):
            rv.append(FacetLink('%s %s' % (app, version), dict(appver=version),
                                appver == version))
    return rv


def platform_sidebar(request, query, facets):
    qplatform = query.get('platform')
    app_platforms = request.APP.platforms.values()
    ALL = app_platforms[0]
    platforms = [facet['term'] for facet in facets['platforms']
                 if facet['term'] != ALL.id]
    all_selected = not qplatform or qplatform == ALL.shortname
    rv = [FacetLink(_(u'All Systems'), dict(platform=ALL.shortname),
                    all_selected)]
    for platform in app_platforms[1:]:
        if platform.id in platforms:
            rv.append(FacetLink(platform.name,
                                dict(platform=platform.shortname),
                                platform.shortname == qplatform))
    return rv


def tag_sidebar(request, query, facets):
    qtag = query.get('tag')
    rv = [FacetLink(_(u'All Tags'), dict(tag=None), not qtag)]
    tags = [facet['term'] for facet in facets['tags']]
    rv += [FacetLink(tag, dict(tag=tag), tag == qtag) for tag in tags]
    return rv


def fix_search_query(query):
    rv = dict((smart_str(k), v) for k, v in query.items())
    changed = False
    # Change old keys to new names.
    keys = {
        'lver': 'appver',
        'pid': 'platform',
    }
    for old, new in keys.items():
        if old in query:
            rv[new] = rv.pop(old)
            changed = True

    # Change old parameter values to new values.
    params = {
        'sort': {
            'newest': 'updated',
            'weeklydownloads': 'users',
            'averagerating': 'rating',
        },
        'platform': dict((str(p.id), p.shortname)
                         for p in amo.PLATFORMS.values())
    }
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
