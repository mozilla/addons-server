import collections
import json as jsonlib
import math
import random
import re

from django.conf import settings
from django.utils import translation
from django.utils.encoding import smart_unicode
from django.template import defaultfilters

from babel import Locale
from babel.support import Format
import jinja2
from jinja2.exceptions import FilterArgumentError
from jingo import register, env
from tower import ugettext as _

import amo
from amo import utils, urlresolvers
from addons.models import Category
from translations.models import Translation
from translations.query import order_by_translation

# Yanking filters from Django.
register.filter(defaultfilters.slugify)

# Registering some utils as filters:
urlparams = register.filter(utils.urlparams)
register.filter(utils.epoch)
register.filter(utils.isotime)
register.function(dict)
register.function(utils.randslice)


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
    add_prefix = kwargs.pop('add_prefix', True)
    return urlresolvers.reverse(viewname,
                                args=args,
                                kwargs=kwargs,
                                add_prefix=add_prefix)


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

    Type = collections.namedtuple('Type', 'name url')
    base = urlresolvers.reverse('home')
    types = [Type(_('Collections'), base + 'collections/')]
    shown_types = {
        amo.ADDON_PERSONA: urlresolvers.reverse('browse.personas'),
        amo.ADDON_DICT: urlresolvers.reverse('browse.language-tools'),
        amo.ADDON_SEARCH: urlresolvers.reverse('browse.search-tools'),
        amo.ADDON_PLUGIN: base + 'browse/type:7',
        amo.ADDON_THEME: urlresolvers.reverse('browse.themes'),
    }
    titles = dict(amo.ADDON_TYPES,
                  **{amo.ADDON_DICT: _('Dictionaries & Language Packs')})
    for type_, url in shown_types.items():
        if type_ in app.types:
            types.append(Type(titles[type_], url))

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


@register.filter
def currencyfmt(num, currency):
    return _get_format().currency(num, currency)


def page_name(app=None):
    """Determine the correct page name for the given app (or no app)."""
    if app:
        return _(u'Add-ons for {0}').format(app.pretty)
    else:
        return _('Add-ons')


@register.function
@jinja2.contextfunction
def login_link(context):
    next = context['request'].path

    qs = context['request'].GET.urlencode()

    if qs:
        next += '?' + qs

    l = urlparams(urlresolvers.reverse('users.login'), to=next)
    return l


@register.function
@jinja2.contextfunction
def page_title(context, title):
    app = context['request'].APP
    return u'%s :: %s' % (smart_unicode(title), page_name(app))


@register.function
@jinja2.contextfunction
def breadcrumbs(context, items=list(), add_default=True):
    """
    show a list of breadcrumbs. If url is None, it won't be a link.
    Accepts: [(url, label)]
    """
    if add_default:
        app = context['request'].APP
        crumbs = [(urlresolvers.reverse('home'), page_name(app))]
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
def json(s):
    return jsonlib.dumps(s)


@register.filter
def absolutify(url):
    """Takes a URL and prepends the SITE_URL"""
    return settings.SITE_URL + url


@register.filter
def strip_controls(s):
    """
    Strips control characters from a string.
    """
    # Translation table of control characters.
    control_trans = dict((n, None) for n in xrange(32) if n not in [10, 13])
    return unicode(s).translate(control_trans)


@register.filter
def strip_html(s, just_kidding=False):
    """Strips HTML.  Confirm lets us opt out easily."""
    if just_kidding:
        return s

    if not s:
        return ''
    else:
        s = re.sub(r'&lt;.*?&gt;', '', smart_unicode(s, errors='ignore'))
        return re.sub(r'<.*?>', '', s)


@register.filter
def external_url(url):
    """Bounce a URL off outgoing.mozilla.org."""
    return urlresolvers.get_outgoing_url(unicode(url))


@register.filter
def shuffle(sequence):
    """Shuffle a sequence."""
    random.shuffle(sequence)
    return sequence


@register.function
def license_link(license):
    """Link to a code license, incl. icon where applicable."""
    if not license:
        return ''
    if not license.builtin:
        return _('Custom License')
    lic_icon = lambda name: '<li class="icon %s"></li>' % name

    parts = []
    parts.append('<ul class="license">')
    if license.icons:
        for i in license.icons.split():
            parts.append(lic_icon(i))

    # TODO link to custom license page
    parts.append('<li class="text">')

    if license.url:
        if license.some_rights:
            title = ' title="%s"' % license.name
            linktext = _('Some rights reserved')
        else:
            title = ''
            linktext = license.name

        parts.append(u'<a href="%s"%s>%s</a>' % (
                     license.url, title, linktext))
    else:
        parts.append(unicode(license.name))
    parts.append('</li></ul>')

    return jinja2.Markup(''.join(parts))


@register.function
def field(field, label=None, **attrs):
    if label is not None:
        field.label = label
    return jinja2.Markup(u'%s<p>%s%s</p>' %
                         (field.errors, field.label_tag(),
                          field.as_widget(attrs=attrs)))


@register.inclusion_tag('amo/category-arrow.html')
@jinja2.contextfunction
def category_arrow(context, key, prefix):
    d = dict(context.items())
    d.update(key=key, prefix=prefix)
    return d


@register.filter
def timesince(time):
    ago = defaultfilters.timesince(time)
    # L10n: relative time in the past, like '4 days ago'
    return _(u'{0} ago').format(ago)
