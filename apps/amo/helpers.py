import cgi
import collections
import json as jsonlib
import math
import urllib
import urlparse

from django.conf import settings
from django.utils import translation
from django.template import defaultfilters

from babel import Locale
from babel.support import Format
import datetime
import jinja2
from jinja2.exceptions import FilterArgumentError
import pytz
import time

from jingo import register, env
from l10n import ugettext as _

import amo
from amo import urlresolvers
from addons.models import Category
from translations.query import order_by_translation

# Yanking filters from Django.
register.filter(defaultfilters.slugify)


@register.function
def locale_url(url):
    """Take a URL and give it the locale prefix."""
    prefixer = urlresolvers.get_url_prefix()
    script = prefixer.request.META['SCRIPT_NAME']
    parts = [script, prefixer.locale, url.lstrip('/')]
    return '/'.join(parts)


@register.function
def url(viewname, *args, **kwargs):
    """Helper for Django's ``reverse`` in templates."""
    return urlresolvers.reverse(viewname, args=args, kwargs=kwargs)


@register.filter
def urlparams(url_, hash=None, **query):
    """
    Add a fragment and/or query paramaters to a URL.

    New query params will be appended to exising parameters, except duplicate
    names, which will be replaced.
    """
    url = urlparse.urlparse(url_)
    fragment = hash if hash is not None else url.fragment

    query_dict = dict(cgi.parse_qsl(url.query)) if url.query else {}
    query_dict.update((k, v) for k, v in query.items() if v is not None)

    query_string = urllib.urlencode(query_dict.items())
    new = urlparse.ParseResult(url.scheme, url.netloc, url.path, url.params,
                               query_string, fragment)
    return new.geturl()


@register.filter
def paginator(pager):
    return Paginator(pager).render()


@register.function
def is_mobile(app):
    return app == amo.MOBILE


@register.function
def sidebar(app):
    """Populates the sidebar with (categories, types)."""
    if app is None:
        return [], []

    # We muck with query to make order_by and extra_order_by play nice.
    q = Category.objects.filter(application=app.id, weight__gte=0,
                                type=amo.ADDON_EXTENSION)
    categories = order_by_translation(q, 'name')
    categories.query.extra_order_by.insert(0, 'weight')

    # TODO(jbalogh): real reverse
    Type = collections.namedtuple('Type', 'name url')
    base = urlresolvers.reverse('home')
    types = [Type(_('Collections'), base + 'collections/')]
    shown_types = {
        amo.ADDON_PERSONA: base + 'personas/',
        amo.ADDON_DICT: urlresolvers.reverse('browse.language_tools'),
        amo.ADDON_SEARCH: base + 'browse/type:4',
        amo.ADDON_PLUGIN: base + 'browse/type:7',
        amo.ADDON_THEME: urlresolvers.reverse('browse.themes'),
    }
    for type_, url in shown_types.items():
        if type_ in app.types:
            name = amo.ADDON_TYPES[type_]
            types.append(Type(name, url))

    return categories, sorted(types, key=lambda x: x.name)


class Paginator(object):

    def __init__(self, pager):
        self.pager = pager

        self.max = 10
        self.span = (self.max - 1) / 2

        self.page = pager.number
        self.num_pages = pager.paginator.num_pages
        self.count = pager.paginator.count

        pager.page_range = self.range()
        pager.dotted_upper = self.num_pages not in pager.page_range
        pager.dotted_lower = 1 not in pager.page_range

    def range(self):
        """Return a list of page numbers to show in the paginator."""
        page, total, span = self.page, self.num_pages, self.span
        if total < self.max:
            lower, upper = 0, total
        elif page < span + 1:
            lower, upper = 0, span * 2
        elif page > total - span:
            lower, upper = total - span * 2, total
        else:
            lower, upper = page - span, page + span - 1
        return range(max(lower + 1, 1), min(total, upper) + 1)

    def render(self):
        c = {'pager': self.pager, 'num_pages': self.num_pages,
             'count': self.count}
        t = env.get_template('amo/paginator.html').render(**c)
        return jinja2.Markup(t)


def _get_format():
    lang = translation.get_language()
    locale = Locale(translation.to_locale(lang))
    return Format(locale)


@register.filter
def numberfmt(num, format=None):
    return _get_format().decimal(num, format)


def _page_name(app=None):
    """Determine the correct page name for the given app (or no app)."""
    if app:
        return _(u'Add-ons for {0}').format(app.pretty)
    else:
        return _('Add-ons')


@register.function
@jinja2.contextfunction
def page_title(context, title):
    app = context['request'].APP
    return u'%s :: %s' % (title, _page_name(app))


@register.function
@jinja2.contextfunction
def breadcrumbs(context, items=list(), add_default=True):
    """
    show a list of breadcrumbs.
    Accepts: [(url, label)]
    """
    if add_default:
        app = context['request'].APP
        crumbs = [(urlresolvers.reverse('home'), _page_name(app))]
    else:
        crumbs = []

    # add user-defined breadcrumbs
    if items:
        try:
            crumbs += items
        except TypeError:
            crumbs.append(items)

    c = {'breadcrumbs': crumbs}
    t = env.get_template('amo/breadcrumbs.html').render(**c)
    return jinja2.Markup(t)


@register.filter
def wround(value, precision=0, method='common'):
    """Round the number to a given precision. The first
    parameter specifies the precision (default is ``0``), the
    second the rounding method:

    - ``'common'`` rounds either up or down
    - ``'ceil'`` always rounds up
    - ``'floor'`` always rounds down

    If you don't specify a method ``'common'`` is used.

    .. sourcecode:: jinja

        {{ 42.55|round }}
            -> 43
        {{ 42.55|round(1, 'floor') }}
            -> 42.5
    """
    if not method in ('common', 'ceil', 'floor'):
        raise FilterArgumentError('method must be common, ceil or floor')
    if precision < 0:
        raise FilterArgumentError('precision must be a postive integer '
                                  'or zero.')
    if method == 'common':
        val = round(value, precision)
        return val if precision else int(val)
    func = getattr(math, method)
    if precision:
        return func(value * 10 * precision) / (10 * precision)
    else:
        return int(func(value))


def _append_tz(t):
    tz = pytz.timezone(settings.TIME_ZONE)
    return tz.localize(t)


@register.filter
def isotime(t):
    """Date/Time format according to ISO 8601"""
    return _append_tz(t).astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S%z")


@register.filter
def epoch(t):
    """Date/Time converted to seconds since epoch"""
    return int(time.mktime(_append_tz(t).timetuple()))


@register.filter
def json(s):
    return jsonlib.dumps(s)


@register.filter
def absolutify(url):
    """Takes a URL and prepends the SITE_URL"""
    return settings.SITE_URL + url
