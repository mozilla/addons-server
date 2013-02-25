from collections import defaultdict

from django import http
from django.conf import settings
from django.db.models import Q
from django.utils.encoding import smart_str
from django.views.decorators.vary import vary_on_headers
from django.utils import translation

from elasticutils.contrib.django import F, S
import commonware.log
import jingo
from mobility.decorators import mobile_template
from tower import ugettext as _

import amo
import bandwagon.views
import browse.views
from addons.models import Addon, Category
from amo.decorators import json_view
from amo.helpers import locale_url, urlparams
from amo.utils import MenuItem, sorted_groupby
from bandwagon.models import Collection
from versions.compare import dict_from_int, version_int, version_dict

import mkt
from mkt.webapps.models import Webapp

from .forms import ESSearchForm, SecondarySearchForm, sort_by


DEFAULT_NUM_COLLECTIONS = 20
DEFAULT_NUM_PERSONAS = 21  # Results appear in a grid of 3 personas x 7 rows.

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

    item = (None, _('Keyword Match'))
    items.append(item)

    for key, val in sort_by:
        if key == '':
            continue
        item = (key, val)
        items.append(item)

    return items


def _get_sorts(request, sort):
    items = []
    url = request.get_full_path()

    item = MenuItem()
    (item.text, item.url) = (_('Keyword Match'), urlparams(url, sort=None))

    if not sort:
        item.selected = True

    items.append(item)

    for key, val in sort_by:
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

    initial = dict(request.GET.items())

    # Ignore these filters since return the same results for Firefox
    # as for Thunderbird, etc.
    initial.update(appver=None, platform=None)

    form = ESSearchForm(initial, type=amo.ADDON_PERSONA)
    form.is_valid()

    qs = Addon.search().filter(status__in=amo.REVIEWED_STATUSES,
                               is_disabled=False)
    filters = ['sort']
    mapping = {'downloads': '-weekly_downloads',
               'users': '-average_daily_users',
               'rating': '-bayesian_rating',
               'created': '-created',
               'name': 'name_sort',
               'updated': '-last_updated',
               'hotness': '-hotness'}
    results = _filter_search(request, qs, form.cleaned_data, filters,
                             sorting=mapping, types=[amo.ADDON_PERSONA])

    query = form.cleaned_data.get('q', '')

    search_opts = {}
    search_opts['limit'] = form.cleaned_data.get('pp', DEFAULT_NUM_PERSONAS)
    page = form.cleaned_data.get('page') or 1
    search_opts['offset'] = (page - 1) * search_opts['limit']

    pager = amo.utils.paginate(request, results, per_page=search_opts['limit'])
    categories, filter, _, _ = browse.views.personas_listing(request)
    c = dict(pager=pager, form=form, categories=categories, query=query,
             filter=filter, search_placeholder='themes')
    return jingo.render(request, 'search/personas.html', c)


def _collections(request):
    """Handle the request for collections."""

    # Sorting by relevance isn't an option. Instead the default is `weekly`.
    initial = dict(sort='weekly')
    # Update with GET variables.
    initial.update(request.GET.items())
    # Ignore appver/platform and set default number of collections per page.
    initial.update(appver=None, platform=None, pp=DEFAULT_NUM_COLLECTIONS)

    form = SecondarySearchForm(initial)
    form.is_valid()

    qs = Collection.search().filter(listed=True, app=request.APP.id)
    filters = ['sort']
    mapping = {'weekly': '-weekly_subscribers',
               'monthly': '-monthly_subscribers',
               'all': '-subscribers',
               'rating': '-rating',
               'created': '-created',
               'name': 'name_sort',
               'updated': '-modified'}
    results = _filter_search(request, qs, form.cleaned_data, filters,
                             sorting=mapping,
                             sorting_default='-weekly_subscribers',
                             types=amo.COLLECTION_SEARCH_CHOICES)

    query = form.cleaned_data.get('q', '')

    search_opts = {}
    search_opts['limit'] = form.cleaned_data.get('pp', DEFAULT_NUM_COLLECTIONS)
    page = form.cleaned_data.get('page') or 1
    search_opts['offset'] = (page - 1) * search_opts['limit']
    search_opts['sort'] = form.cleaned_data.get('sort')

    pager = amo.utils.paginate(request, results, per_page=search_opts['limit'])
    c = dict(pager=pager, form=form, query=query, opts=search_opts,
             filter=bandwagon.views.get_filter(request),
             search_placeholder='collections')
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

    def __init__(self, request, excluded_ids=()):
        self.request = request
        self.excluded_ids = excluded_ids
        self.src = getattr(self, 'src', None)
        self.types = getattr(self, 'types', amo.ADDON_TYPES.keys())
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

    def queryset(self):
        """Get items based on ID or search by name."""
        results = Addon.objects.none()
        q = self.request.GET.get(self.key)
        if q:
            pk = None
            try:
                pk = int(q)
            except ValueError:
                pass
            qs = None
            if pk:
                qs = Addon.objects.filter(id=int(q), disabled_by_user=False)
            elif len(q) > 2:
                # Oh, how I wish I could elastically exclude terms.
                # (You can now, but I forgot why I was complaining to
                # begin with.)
                qs = (S(Addon).query(or_=name_only_query(q.lower()))
                      .filter(is_disabled=False))
            if qs:
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

    @property
    def items(self):
        return self.build_list()


class SearchSuggestionsAjax(BaseAjaxSearch):
    src = 'mkt-ss' if settings.MARKETPLACE else 'ss'


class AddonSuggestionsAjax(SearchSuggestionsAjax):
    # No personas. No webapps.
    types = [amo.ADDON_ANY, amo.ADDON_EXTENSION, amo.ADDON_THEME,
             amo.ADDON_DICT, amo.ADDON_SEARCH, amo.ADDON_LPAPP]


class PersonaSuggestionsAjax(SearchSuggestionsAjax):
    types = [amo.ADDON_PERSONA]


class WebappSuggestionsAjax(SearchSuggestionsAjax):
    types = [amo.ADDON_WEBAPP]
    fields = {'url': 'get_url_path', 'name': 'name', 'id': 'id'}

    def __init__(self, request, excluded_ids=(), category=None):
        self.category = category
        self.gaia = getattr(request, 'GAIA', False)
        self.mobile = getattr(request, 'MOBILE', False)
        self.tablet = getattr(request, 'TABLET', False)
        SearchSuggestionsAjax.__init__(self, request, excluded_ids)
        if self.mobile:
            self.limit = 3

    def queryset(self):
        res = SearchSuggestionsAjax.queryset(self)
        if self.category:
            res = res.filter(category__in=[self.category])
        if (self.mobile or self.tablet) and not self.gaia:
            if isinstance(res, S):
                res = res.filter(~F(premium_type__in=amo.ADDON_PREMIUMS,
                                    price__gt=0))
            else:
                res.exclude(premium_type__in=amo.ADDON_PREMIUMS, price__gt=0)

        region = getattr(self.request, 'REGION', mkt.regions.WORLDWIDE)
        if region:
            excluded = Webapp.get_excluded_in(region)
            if excluded:
                if isinstance(res, S):
                    # ES? Do fanciness.
                    res = res.filter(~F(id__in=excluded))
                else:
                    # Django ORM? Do an `exclude`.
                    res = res.exclude(id__in=excluded)

        if self.gaia:
            res = res.filter(device=amo.DEVICE_GAIA.id, uses_flash=False)
        elif self.mobile:
            res = res.filter(device=amo.DEVICE_MOBILE.id, uses_flash=False)

        return res


@json_view
def ajax_search(request):
    """This is currently used only to return add-ons for populating a
    new collection. Personas are included by default, so this can be
    used elsewhere.

    """
    search_obj = BaseAjaxSearch(request)
    search_obj.types = amo.ADDON_SEARCH_TYPES
    return search_obj.items


@json_view
def ajax_search_suggestions(request):
    results = []
    q = request.GET.get('q')
    if q and (q.isdigit() or len(q) > 2):
        q_ = q.lower()

        cat = request.GET.get('cat', 'all')

        # Don't let Marketplace query any other types.
        if settings.MARKETPLACE:
            cat = 'apps'

        if cat != 'apps':
            # Applications.
            for a in amo.APP_USAGE:
                name_ = unicode(a.pretty).lower()
                word_matches = [w for w in q_.split() if name_ in w]
                if q_ in name_ or word_matches:
                    results.append({
                        'id': a.id,
                        'name': _(u'{0} Add-ons').format(a.pretty),
                        'url': locale_url(a.short),
                        'cls': 'app ' + a.short
                    })

        # Categories.
        cats = Category.objects
        if cat == 'apps':
            cats = cats.filter(type=amo.ADDON_WEBAPP)
        else:
            cats = cats.filter(Q(application=request.APP.id) |
                               Q(type=amo.ADDON_SEARCH))
            if cat == 'themes':
                cats = cats.filter(type=amo.ADDON_PERSONA)
            else:
                cats = cats.exclude(type__in=[amo.ADDON_PERSONA,
                                              amo.ADDON_WEBAPP])

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
            'themes': PersonaSuggestionsAjax,
            'apps': WebappSuggestionsAjax,
        }.get(cat, AddonSuggestionsAjax)

        results += suggestions(request).items

    return results


def _get_locale_analyzer():
    return amo.SEARCH_LANGUAGE_TO_ANALYZER.get(translation.get_language())


def name_only_query(q):
    d = {}

    rules = {'text': {'query': q, 'boost': 3, 'analyzer': 'standard'},
             'text': {'query': q, 'boost': 4, 'type': 'phrase'},
             'fuzzy': {'value': q, 'boost': 2, 'prefix_length': 4},
             'startswith': {'value': q, 'boost': 1.5}}
    for k, v in rules.iteritems():
        for field in ('name', 'slug', 'app_slug', 'authors'):
            d['%s__%s' % (field, k)] = v

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
        more['summary_%s__text' % analyzer] = {'query': q,
                                               'boost': 0.6,
                                               'type': 'phrase',
                                               'analyzer': analyzer}
        more['description_%s__text' % analyzer] = {'query': q,
                                                   'boost': 0.1,
                                                   'type': 'phrase',
                                                   'analyzer': analyzer}
    return dict(more, **name_only_query(q))


def _filter_search(request, qs, query, filters, sorting,
                   sorting_default='-weekly_downloads', types=[]):
    """Filter an ES queryset based on a list of filters."""
    APP = request.APP
    # Intersection of the form fields present and the filters we want to apply.
    show = [f for f in filters if query.get(f)]

    if query.get('q'):
        qs = qs.query(or_=name_query(query['q']))
    if 'platform' in show and query['platform'] in amo.PLATFORM_DICT:
        ps = (amo.PLATFORM_DICT[query['platform']].id, amo.PLATFORM_ALL.id)
        # If we've selected "All Systems" don't filter by platform.
        if ps[0] != ps[1]:
            qs = qs.filter(platform__in=ps)
    if 'appver' in show:
        # Get a min version less than X.0.
        low = version_int(query['appver'])
        # Get a max version greater than X.0a.
        high = version_int(query['appver'] + 'a')
        # If we're not using D2C then fall back to appversion checking.
        extensions_shown = (not query.get('atype') or
                            query['atype'] == amo.ADDON_EXTENSION)
        if not extensions_shown or low < version_int('10.0'):
            qs = qs.filter(**{'appversion.%s.max__gte' % APP.id: high,
                              'appversion.%s.min__lte' % APP.id: low})
    if 'atype' in show and query['atype'] in amo.ADDON_TYPES:
        qs = qs.filter(type=query['atype'])
    else:
        qs = qs.filter(type__in=types)
    if 'cat' in show:
        if amo.ADDON_WEBAPP not in types:
            cat = (Category.objects.filter(id=query['cat'])
                   .filter(Q(application=APP.id) | Q(type=amo.ADDON_SEARCH)))
            if not cat.exists():
                show.remove('cat')
        if 'cat' in show:
            qs = qs.filter(category=query['cat'])
    if 'tag' in show:
        qs = qs.filter(tag=query['tag'])
    if 'sort' in show:
        qs = qs.order_by(sorting[query['sort']])
    elif not query.get('q'):
        # Sort by a default if there was no query so results are predictable.
        qs = qs.order_by(sorting_default)

    return qs


@mobile_template('search/{mobile/}results.html')
@vary_on_headers('X-PJAX')
def search(request, tag_name=None, template=None):
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
        return http.HttpResponsePermanentRedirect(urlparams(request.path,
                                                            **fixed))

    form = ESSearchForm(request.GET or {})
    form.is_valid()  # Let the form try to clean data.

    query = form.cleaned_data
    if tag_name:
        query['tag'] = tag_name

    if category == 'collections':
        return _collections(request)
    elif category == 'themes' or query.get('atype') == amo.ADDON_PERSONA:
        return _personas(request)

    sort, extra_sort = split_choices(form.sort_choices, 'created')
    if query.get('atype') == amo.ADDON_SEARCH:
        # Search add-ons should not be searched by ADU, so replace 'Users'
        # sort with 'Weekly Downloads'.
        sort, extra_sort = list(sort), list(extra_sort)
        sort[1] = extra_sort[1]
        del extra_sort[1]

    qs = (Addon.search()
          .filter(status__in=amo.REVIEWED_STATUSES, is_disabled=False,
                  app=APP.id)
          .facet(tags={'terms': {'field': 'tag'}},
                 platforms={'terms': {'field': 'platform'}},
                 appversions={'terms':
                              {'field': 'appversion.%s.max' % APP.id}},
                 categories={'terms': {'field': 'category', 'size': 200}}))

    filters = ['atype', 'appver', 'cat', 'sort', 'tag', 'platform']
    mapping = {'users': '-average_daily_users',
               'rating': '-bayesian_rating',
               'created': '-created',
               'name': 'name_sort',
               'downloads': '-weekly_downloads',
               'updated': '-last_updated',
               'hotness': '-hotness'}
    qs = _filter_search(request, qs, query, filters, mapping, types=types)

    pager = amo.utils.paginate(request, qs)

    ctx = {
        'is_pjax': request.META.get('HTTP_X_PJAX'),
        'pager': pager,
        'query': query,
        'form': form,
        'sort_opts': sort,
        'extra_sort_opts': extra_sort,
        'sorting': sort_sidebar(request, query, form),
        'sort': query.get('sort'),
    }
    if not ctx['is_pjax']:
        facets = pager.object_list.facets
        ctx.update({
            'tag': tag_name,
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
            for key, text in form.sort_choices]


def category_sidebar(request, query, facets):
    APP = request.APP
    qatype, qcat = query.get('atype'), query.get('cat')
    webapp = qatype == amo.ADDON_WEBAPP
    cats = [f['term'] for f in facets['categories']]
    categories = Category.objects.filter(id__in=cats)
    if qatype in amo.ADDON_TYPES:
        categories = categories.filter(type=qatype)
    if not webapp:
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

    categories = [(atype, sorted(cats, key=lambda x: x.name))
                  for atype, cats in sorted_groupby(categories, 'type')]

    rv = []
    cat_params = dict(cat=None)
    all_label = _(u'All Apps') if webapp else _(u'All Add-ons')

    if not webapp or (webapp and not categories):
        rv = [FacetLink(all_label, dict(atype=None, cat=None), not qatype)]

    for addon_type, cats in categories:
        selected = (webapp and not qatype) or addon_type == qatype and not qcat

        # Build the linkparams.
        cat_params = cat_params.copy()
        if not webapp:
            cat_params.update(atype=addon_type)

        link = FacetLink(all_label if webapp else amo.ADDON_TYPES[addon_type],
                         cat_params, selected)
        link.children = [FacetLink(c.name, dict(cat_params, **dict(cat=c.id)),
                                   c.id == qcat) for c in cats]
        rv.append(link)
    return rv


def version_sidebar(request, query, facets):
    appver = query.get('appver')
    app = unicode(request.APP.pretty)
    exclude_versions = getattr(request.APP, 'exclude_versions', [])
    # L10n: {0} is an application, such as Firefox. This means "any version of
    # Firefox."
    rv = [FacetLink(_(u'Any {0}').format(app), dict(appver=''), not appver)]
    vs = [dict_from_int(f['term']) for f in facets['appversions']]

    # Insert the filtered app version even if it's not a facet.
    av_dict = version_dict(appver)

    if av_dict and av_dict not in vs and av_dict['major']:
        vs.append(av_dict)

    # Valid versions must be in the form of `major.minor`.
    vs = set((v['major'], v['minor1'] if v['minor1'] not in (None, 99) else 0)
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
    ALL = app_platforms.pop(0)

    # The default is to show "All Systems."
    selected = amo.PLATFORM_DICT.get(qplatform, ALL)

    if selected != ALL and selected not in app_platforms:
        # Insert the filtered platform even if it's not a facet.
        app_platforms.append(selected)

    # L10n: "All Systems" means show everything regardless of platform.
    rv = [FacetLink(_(u'All Systems'), dict(platform=ALL.shortname),
                    selected == ALL)]
    for platform in app_platforms:
        rv.append(FacetLink(platform.name, dict(platform=platform.shortname),
                            platform == selected))
    return rv


def tag_sidebar(request, query, facets):
    qtag = query.get('tag')
    tags = [facet['term'] for facet in facets['tags']]
    rv = [FacetLink(_(u'All Tags'), dict(tag=None), not qtag)]
    rv += [FacetLink(tag, dict(tag=tag), tag == qtag) for tag in tags]
    if qtag and qtag not in tags:
        rv += [FacetLink(qtag, dict(tag=qtag), True)]
    return rv


def fix_search_query(query, extra_params=None):
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
            'popularity': 'downloads',
            'weeklydownloads': 'users',
            'averagerating': 'rating',
            'sortby': 'sort',
        },
        'platform': dict((str(p.id), p.shortname)
                         for p in amo.PLATFORMS.values())
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
