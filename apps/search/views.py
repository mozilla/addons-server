from collections import defaultdict

from django.conf import settings
from django.db.models import Q
from django.shortcuts import redirect
from django.utils.encoding import smart_str

import commonware.log
import jingo
from tower import ugettext as _
from mobility.decorators import mobile_template

import amo
import bandwagon.views
import browse.views
from addons.models import Addon, Category
from amo.decorators import json_view
from amo.helpers import urlparams
from amo.utils import MenuItem, sorted_groupby
from versions.compare import dict_from_int, version_int
from webapps.models import Webapp

from . import forms
from .client import (Client as SearchClient, SearchError,
                           CollectionsClient, PersonasClient, sphinx)
from .forms import SearchForm, SecondarySearchForm, ESSearchForm

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


@json_view
def ajax_search(request):
    """ Returns a json feed of ten results for auto-complete used in
    collections.
    [
        {"id": 123, "name": "best addon", "icon": "http://path/to/icon"},
        ...
    ]
    """
    # TODO(cvan): Replace with better ES-powered JSON views. Coming soon.
    results = []
    if 'q' in request.GET:
        if settings.USE_ELASTIC:
            q = request.GET['q']
            exclude_personas = request.GET.get('exclude_personas', False)
            if q.isdigit():
                qs = Addon.objects.filter(id=int(q))
            else:
                qs = Addon.search().query(or_=name_query(q))
            types = amo.ADDON_SEARCH_TYPES[:]
            if exclude_personas:
                types.remove(amo.ADDON_PERSONA)
            qs = qs.filter(type__in=types)
            results = qs.filter(status__in=amo.REVIEWED_STATUSES,
                                is_disabled=False)[:10]
        else:
            # TODO: Let this die when we kill Sphinx.
            q = request.GET.get('q', '')
            client = SearchClient()
            try:
                results = client.query('@name ' + q, limit=10,
                                       match=sphinx.SPH_MATCH_EXTENDED2)
            except SearchError:
                pass
    return [dict(id=result.id, label=unicode(result.name),
                 url=result.get_url_path(), icon=result.icon_url,
                 value=unicode(result.name).lower())
            for result in results]



def name_query(q):
    # 1. Prefer text matches first (boost=3).
    # 2. Then try fuzzy matches ("fire bug" => firebug) (boost=2).
    # 3. Then look for the query as a prefix of a name (boost=1.5).
    # 4. Look for text matches inside the summary (boost=0.8).
    # 5. Look for text matches inside the description (boost=0.3).
    return dict(name__text={'query': q, 'boost': 3},
                name__fuzzy={'value': q, 'boost': 2, 'prefix_length': 4},
                name__startswith={'value': q, 'boost': 1.5},
                summary__text={'query': q, 'boost': 0.8},
                description__text={'query': q, 'boost': 0.3})


@mobile_template('search/es_results.html')
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
        'pager': pager,
        'query': query,
        'form': form,
        'sorting': sort_sidebar(request, query, form),
        'categories': category_sidebar(request, query, facets),
        'tags': tag_sidebar(request, query, facets),
    }
    return jingo.render(request, template, ctx)


@mobile_template('search/es_results.html')
def es_search(request, tag_name=None, template=None):
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

    qs = (Addon.search().query(or_=name_query(query['q']))
          .filter(status__in=amo.REVIEWED_STATUSES, is_disabled=False,
                  app=APP.id)
          .facet(tags={'terms': {'field': 'tag'}},
                 platforms={'terms': {'field': 'platform'}},
                 appversions={'terms':
                              {'field': 'appversion.%s.max' % APP.id}},
                 categories={'terms': {'field': 'category', 'size': 100}}))
    if query.get('tag'):
        qs = qs.filter(tag=query['tag'])
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

    pager = amo.utils.paginate(request, qs)
    facets = pager.object_list.facets

    ctx = {
        'pager': pager,
        'query': query,
        'form': form,
        'sort_opts': sort,
        'extra_sort_opts': extra_sort,
        'sorting': sort_sidebar(request, query, form),
        'categories': category_sidebar(request, query, facets),
        'platforms': platform_sidebar(request, query, facets),
        'versions': version_sidebar(request, query, facets),
        'tags': tag_sidebar(request, query, facets),
    }
    return jingo.render(request, template, ctx)


@mobile_template('search/{mobile/}results.html')
def search(request, tag_name=None, template=None):
    # If the form is invalid we still want to have a query.
    query = request.REQUEST.get('q', '')

    search_opts = {
            'meta': ('versions', 'categories', 'tags', 'platforms'),
            'version': None,
            }

    form = SearchForm(request)
    form.is_valid()  # Let the form try to clean data.

    category = form.cleaned_data.get('cat')

    if category == 'collections':
        return _collections(request)
    elif category == 'personas':
        return _personas(request)

    # TODO: Let's change the form values to something less gross when
    # Remora dies in a fire.
    query = form.cleaned_data['q']

    addon_type = form.cleaned_data.get('atype', 0)
    tag = tag_name if tag_name is not None else form.cleaned_data.get('tag')
    if tag_name:
        search_opts['show_personas'] = True
    page = form.cleaned_data['page']
    sort = form.cleaned_data.get('sort')

    search_opts['version'] = form.cleaned_data.get('lver')
    search_opts['limit'] = form.cleaned_data.get('pp', DEFAULT_NUM_RESULTS)
    search_opts['platform'] = form.cleaned_data.get('pid', amo.PLATFORM_ALL)
    search_opts['sort'] = sort
    search_opts['app'] = request.APP.id
    search_opts['offset'] = (page - 1) * search_opts['limit']

    if category:
        search_opts['category'] = category
    elif addon_type:
        search_opts['type'] = addon_type

    search_opts['tag'] = tag

    client = SearchClient()

    try:
        results = client.query(query, **search_opts)
    except SearchError, e:
        log.error('Sphinx Error: %s' % e)
        return jingo.render(request, 'search/down.html', locals(), status=503)

    version_filters = client.meta['versions']

    # If we are filtering by a version, make sure we explicitly list it.
    if search_opts['version']:
        try:
            version_filters += (version_int(search_opts['version']),)
        except UnicodeEncodeError:
            pass  # We didn't want to list you anyway.

    versions = _get_versions(request, client.meta['versions'],
                             search_opts['version'])
    categories = _get_categories(request, client.meta['categories'],
                                 addon_type, category)
    tags = _get_tags(request, client.meta['tags'], tag)
    platforms = _get_platforms(request, client.meta['platforms'],
                               search_opts['platform'])
    sort_tabs = _get_sorts(request, sort)
    sort_opts = _get_sort_menu(request, sort)

    pager = amo.utils.paginate(request, results, search_opts['limit'])

    context = dict(pager=pager, query=query, tag=tag, platforms=platforms,
                   versions=versions, categories=categories, tags=tags,
                   sort_tabs=sort_tabs, sort_opts=sort_opts, sort=sort)
    return jingo.render(request, template, context)


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
