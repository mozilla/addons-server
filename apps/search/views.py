from collections import defaultdict
from datetime import timedelta, datetime
import time

from django.http import HttpResponseRedirect

import commonware.log
import jingo
from tower import ugettext as _

import amo
import bandwagon.views
import browse.views
from amo.decorators import json_view
from amo.helpers import urlparams
from amo import urlresolvers
from versions.compare import dict_from_int, version_int
from search import forms
from search.client import (Client as SearchClient, SearchError,
                           CollectionsClient, PersonasClient, sphinx)
from search.forms import SearchForm, SecondarySearchForm

DEFAULT_NUM_RESULTS = 20

log = commonware.log.getLogger('z.search')


class MenuItem():
    url, text, selected, children = ('', '', False, [])


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
        v_float = v['major'] + v['minor1'] / 10.0
        text = "%0.1f" % v_float

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
        # TODO(davedash): Remove 'name' altogether if nobody complains.
        if key == '' or key == 'name':
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

    q = request.GET.get('q', '')
    client = SearchClient()
    try:

        results = client.query('@name ' + q, limit=10,
                               match=sphinx.SPH_MATCH_EXTENDED2)
        return [dict(id=result.id, label=unicode(result.name),
                     icon=result.icon_url, value=unicode(result.name).lower())
                for result in results]
    except SearchError:
        return []


def search(request, tag_name=None):
    # If the form is invalid we still want to have a query.
    query = request.REQUEST.get('q', '')

    search_opts = {
            'meta': ('versions', 'categories', 'tags'),
            'version': None,
            }

    form = SearchForm(request)
    form.is_valid()  # Let the form try to clean data.

    # TODO(davedash): remove this feature when we remove Application for
    # the search advanced form
    # Redirect if appid != request.APP.id

    appid = form.cleaned_data['appid']

    if request.APP.id != appid:
        new_app = amo.APP_IDS.get(appid)
        return HttpResponseRedirect(
                urlresolvers.get_app_redirect(new_app))

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
    page = form.cleaned_data['page']
    last_updated = form.cleaned_data.get('lup')
    sort = form.cleaned_data.get('sort')

    search_opts['version'] = form.cleaned_data.get('lver')
    search_opts['limit'] = form.cleaned_data.get('pp', DEFAULT_NUM_RESULTS)
    search_opts['platform'] = form.cleaned_data.get('pid', amo.PLATFORM_ALL)
    search_opts['sort'] = sort
    search_opts['app'] = request.APP.id
    search_opts['offset'] = (page - 1) * search_opts['limit']

    delta_dict = {
            '1 day ago': timedelta(days=1),
            '1 week ago': timedelta(days=7),
            '1 month ago': timedelta(days=30),
            '3 months ago': timedelta(days=90),
            '6 months ago': timedelta(days=180),
            '1 year ago': timedelta(days=365),
            }

    delta = delta_dict.get(last_updated)

    if delta:
        search_opts['before'] = int(
                time.mktime((datetime.now() - delta).timetuple()))

    if category:
        search_opts['category'] = category
    elif addon_type:
        search_opts['type'] = addon_type

    search_opts['tag'] = tag

    client = SearchClient()

    try:
        results = client.query(query, **search_opts)
    except SearchError, e:
        log.error('Sphinx Error: %s' %e)
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
    sort_tabs = _get_sorts(request, sort)

    pager = amo.utils.paginate(request, results, search_opts['limit'])

    return jingo.render(request, 'search/results.html', {
                'pager': pager, 'query': query, 'tag': tag,
                'versions': versions, 'categories': categories, 'tags': tags,
                'sort_tabs': sort_tabs, 'sort': sort})
