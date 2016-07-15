import collections
import decimal
import json as jsonlib
import os
import random
import re
from operator import attrgetter
from urlparse import urljoin

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.forms import CheckboxInput
from django.utils.translation import (
    ugettext as _, trim_whitespace, to_locale, get_language)
from django.utils.encoding import smart_unicode
from django.utils.html import format_html
from django.template import defaultfilters

import caching.base as caching
import jinja2
import waffle
from babel.support import Format
from jingo import register, get_env
# Needed to make sure our own |f filter overrides jingo's one.
from jingo import helpers  # noqa
from jingo_minify.helpers import (
    _build_html, _get_compiled_css_url, get_path, is_external)

from olympia import amo
from olympia.amo import utils, urlresolvers
from olympia.constants.licenses import PERSONA_LICENSES_IDS
from olympia.translations.query import order_by_translation
from olympia.translations.helpers import truncate

# Yanking filters from Django.
register.filter(defaultfilters.slugify)

# Registering some utils as filters:
urlparams = register.filter(utils.urlparams)
register.filter(utils.epoch)
register.filter(utils.isotime)
register.function(dict)
register.function(utils.randslice)


@register.function
def switch_is_active(switch_name):
    return waffle.switch_is_active(switch_name)


@register.filter
def link(item):
    html = """<a href="%s">%s</a>""" % (item.get_url_path(),
                                        jinja2.escape(item.name))
    return jinja2.Markup(html)


@register.filter
def xssafe(value):
    """
    Like |safe but for strings with interpolation.

    By using |xssafe you assert that you have written tests proving an
    XSS can't happen here.
    """
    return jinja2.Markup(value)


@register.filter
def babel_datetime(dt, format='medium'):
    return _get_format().datetime(dt, format=format) if dt else ''


@register.filter
def babel_date(date, format='medium'):
    return _get_format().date(date, format=format) if date else ''


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
    host = kwargs.pop('host', '')
    src = kwargs.pop('src', '')
    url = '%s%s' % (host, urlresolvers.reverse(viewname,
                                               args=args,
                                               kwargs=kwargs,
                                               add_prefix=add_prefix))
    if src:
        url = urlparams(url, src=src)
    return url


@register.function
def services_url(viewname, *args, **kwargs):
    """Helper for ``url`` with host=SERVICES_URL."""
    kwargs.update({'host': settings.SERVICES_URL})
    return url(viewname, *args, **kwargs)


@register.filter
def paginator(pager):
    return Paginator(pager).render()


@register.filter
def impala_paginator(pager):
    t = get_env().get_template('amo/impala/paginator.html')
    return jinja2.Markup(t.render({'pager': pager}))


@register.filter
def mobile_paginator(pager):
    t = get_env().get_template('amo/mobile/paginator.html')
    return jinja2.Markup(t.render({'pager': pager}))


@register.filter
def mobile_impala_paginator(pager):
    # Impala-style paginator that is easier to mobilefy.
    t = get_env().get_template('amo/mobile/impala_paginator.html')
    return jinja2.Markup(t.render({'pager': pager}))


@register.function
def is_mobile(app):
    return app == amo.MOBILE


@register.function
def sidebar(app):
    """Populates the sidebar with (categories, types)."""
    from olympia.addons.models import Category
    if app is None:
        return [], []

    # We muck with query to make order_by and extra_order_by play nice.
    q = Category.objects.filter(application=app.id, weight__gte=0,
                                type=amo.ADDON_EXTENSION)
    categories = order_by_translation(q, 'name')
    categories.query.extra_order_by.insert(0, 'weight')

    Type = collections.namedtuple('Type', 'id name url')
    base = urlresolvers.reverse('home')
    types = [Type(99, _('Collections'), base + 'collections/')]

    shown_types = {
        amo.ADDON_PERSONA: urlresolvers.reverse('browse.personas'),
        amo.ADDON_DICT: urlresolvers.reverse('browse.language-tools'),
        amo.ADDON_SEARCH: urlresolvers.reverse('browse.search-tools'),
        amo.ADDON_THEME: urlresolvers.reverse('browse.themes'),
    }
    titles = dict(amo.ADDON_TYPES,
                  **{amo.ADDON_DICT: _('Dictionaries & Language Packs')})
    for type_, url in shown_types.items():
        if type_ in app.types:
            types.append(Type(type_, titles[type_], url))

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
        t = get_env().get_template('amo/paginator.html').render(c)
        return jinja2.Markup(t)


def _get_format():
    lang = get_language()
    return Format(utils.get_locale_from_lang(lang))


@register.filter
def numberfmt(num, format=None):
    return _get_format().decimal(num, format)


@register.filter
def currencyfmt(num, currency):
    if num is None:
        return ''
    return _get_format().currency(decimal.Decimal(num), currency)


def page_name(app=None):
    """Determine the correct page name for the given app (or no app)."""
    if app:
        return _(u'Add-ons for {0}').format(app.pretty)
    else:
        return _('Add-ons')


def link_with_final_destination(context, base):
    next_path = context['request'].path

    qs = context['request'].GET.urlencode()

    if qs:
        next_path += '?' + qs

    return urlparams(base, to=next_path)


@register.function
@jinja2.contextfunction
def login_link(context):
    return link_with_final_destination(
        context, urlresolvers.reverse('users.login'))


@register.function
@jinja2.contextfunction
def register_link(context):
    return link_with_final_destination(
        context, urlresolvers.reverse('users.register'))


@register.function
@jinja2.contextfunction
def page_title(context, title):
    title = smart_unicode(title)
    base_title = page_name(context['request'].APP)
    # The following line doesn't use string formatting because we want to
    # preserve the type of `title` in case it's a jinja2 `Markup` (safe,
    # escaped) object.
    return format_html(u'{} :: {}', title, base_title)


@register.function
@jinja2.contextfunction
def breadcrumbs(context, items=list(), add_default=True, crumb_size=40):
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

    crumbs = [(url, truncate(label, crumb_size)) for (url, label) in crumbs]
    c = {'breadcrumbs': crumbs}
    t = get_env().get_template('amo/breadcrumbs.html').render(c)
    return jinja2.Markup(t)


@register.function
@jinja2.contextfunction
def impala_breadcrumbs(context, items=list(), add_default=True, crumb_size=40):
    """
    show a list of breadcrumbs. If url is None, it won't be a link.
    Accepts: [(url, label)]
    """
    if add_default:
        base_title = page_name(context['request'].APP)
        crumbs = [(urlresolvers.reverse('home'), base_title)]
    else:
        crumbs = []

    # add user-defined breadcrumbs
    if items:
        try:
            crumbs += items
        except TypeError:
            crumbs.append(items)

    crumbs = [(url, truncate(label, crumb_size)) for (url, label) in crumbs]
    c = {'breadcrumbs': crumbs, 'has_home': add_default}
    t = get_env().get_template('amo/impala/breadcrumbs.html').render(c)
    return jinja2.Markup(t)


@register.filter
def json(s):
    return jsonlib.dumps(s)


@register.filter
def absolutify(url, site=None):
    """Takes a URL and prepends the SITE_URL"""
    if url.startswith('http'):
        return url
    else:
        return urljoin(site or settings.SITE_URL, url)


@register.filter
def strip_controls(s):
    """
    Strips control characters from a string.
    """
    # Translation table of control characters.
    control_trans = dict((n, None) for n in xrange(32) if n not in [10, 13])
    rv = unicode(s).translate(control_trans)
    return jinja2.Markup(rv) if isinstance(s, jinja2.Markup) else rv


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
    """Bounce a URL off outgoing.prod.mozaws.net."""
    return urlresolvers.get_outgoing_url(unicode(url))


@register.filter
def shuffle(sequence):
    """Shuffle a sequence."""
    random.shuffle(sequence)
    return sequence


@register.function
def license_link(license):
    """Link to a code license, including icon where applicable."""
    # If passed in an integer, try to look up the License.
    from olympia.versions.models import License
    if isinstance(license, (long, int)):
        if license in PERSONA_LICENSES_IDS:
            # Grab built-in license.
            license = PERSONA_LICENSES_IDS[license]
        else:
            # Grab custom license.
            license = License.objects.filter(id=license)
            if not license.exists():
                return ''
            license = license[0]
    elif not license:
        return ''

    if not getattr(license, 'builtin', True):
        return _('Custom License')

    template = get_env().get_template('amo/license_link.html')
    return jinja2.Markup(template.render({'license': license}))


@register.function
def field(field, label=None, **attrs):
    if label is not None:
        field.label = label
    # HTML from Django is already escaped.
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
    if not time:
        return u''
    ago = defaultfilters.timesince(time)
    # L10n: relative time in the past, like '4 days ago'
    return _(u'{0} ago').format(ago)


@register.inclusion_tag('amo/recaptcha.html')
@jinja2.contextfunction
def recaptcha(context, form):
    d = dict(context.items())
    d.update(form=form)
    return d


@register.filter
def is_choice_field(value):
    try:
        return isinstance(value.field.widget, CheckboxInput)
    except AttributeError:
        pass


@register.inclusion_tag('amo/mobile/sort_by.html')
def mobile_sort_by(base_url, options=None, selected=None, extra_sort_opts=None,
                   search_filter=None):
    if search_filter:
        selected = search_filter.field
        options = search_filter.opts
        if hasattr(search_filter, 'extras'):
            options += search_filter.extras
    if extra_sort_opts:
        options_dict = dict(options + extra_sort_opts)
    else:
        options_dict = dict(options)
    if selected in options_dict:
        current = options_dict[selected]
    else:
        selected, current = options[0]  # Default to the first option.
    return locals()


@register.function
@jinja2.contextfunction
def cache_buster(context, url):
    if 'BUILD_ID' in context:
        build = context['BUILD_ID']
    else:
        if url.endswith('.js'):
            build = context['BUILD_ID_JS']
        elif url.endswith('.css'):
            build = context['BUILD_ID_CSS']
        else:
            build = context['BUILD_ID_IMG']
    return utils.urlparams(url, b=build)


@register.function
@jinja2.contextfunction
def media(context, url):
    """Get a MEDIA_URL link with a cache buster querystring."""
    return urljoin(settings.MEDIA_URL, cache_buster(context, url))


@register.function
@jinja2.contextfunction
def static(context, url):
    """Get a STATIC_URL link with a cache buster querystring."""
    return urljoin(settings.STATIC_URL, cache_buster(context, url))


@register.function
@jinja2.evalcontextfunction
def attrs(ctx, *args, **kw):
    return jinja2.filters.do_xmlattr(ctx, dict(*args, **kw))


@register.function
@jinja2.contextfunction
def side_nav(context, addon_type, category=None):
    app = context['request'].APP.id
    cat = str(category.id) if category else 'all'
    return caching.cached(lambda: _side_nav(context, addon_type, category),
                          'side-nav-%s-%s-%s' % (app, addon_type, cat))


def _side_nav(context, addon_type, cat):
    # Prevent helpers generating circular imports.
    from olympia.addons.models import Category, Addon
    request = context['request']
    qs = Category.objects.filter(weight__gte=0)
    if addon_type != amo.ADDON_PERSONA:
        qs = qs.filter(application=request.APP.id)
    sort_key = attrgetter('weight', 'name')
    categories = sorted(qs.filter(type=addon_type), key=sort_key)
    if cat:
        base_url = cat.get_url_path()
    else:
        base_url = Addon.get_type_url(addon_type)
    ctx = dict(request=request, base_url=base_url, categories=categories,
               addon_type=addon_type, amo=amo)
    template = get_env().get_template('amo/side_nav.html')
    return jinja2.Markup(template.render(ctx))


@register.function
@jinja2.contextfunction
def site_nav(context):
    app = context['request'].APP.id
    return caching.cached(lambda: _site_nav(context), 'site-nav-%s' % app)


def _site_nav(context):
    # Prevent helpers from generating circular imports.
    from olympia.addons.models import Category
    request = context['request']

    def sorted_cats(qs):
        return sorted(qs, key=attrgetter('weight', 'name'))

    extensions = Category.objects.filter(
        application=request.APP.id, weight__gte=0, type=amo.ADDON_EXTENSION)
    personas = Category.objects.filter(weight__gte=0, type=amo.ADDON_PERSONA)

    ctx = dict(request=request, amo=amo,
               extensions=sorted_cats(extensions),
               personas=sorted_cats(personas))
    template = get_env().get_template('amo/site_nav.html')
    return jinja2.Markup(template.render(ctx))


@register.function
def loc(s):
    """A noop function for strings that are not ready to be localized."""
    return trim_whitespace(s)


@register.function
def site_event_type(type):
    return amo.SITE_EVENT_CHOICES[type]


@register.function
@jinja2.contextfunction
def remora_url(context, url, lang=None, app=None, prefix=''):
    """Wrapper for urlresolvers.remora_url"""
    if lang is None:
        _lang = context['LANG']
        if _lang:
            lang = to_locale(_lang).replace('_', '-')
    if app is None:
        try:
            app = context['APP'].short
        except (AttributeError, KeyError):
            pass
    return urlresolvers.remora_url(url=url, lang=lang, app=app, prefix=prefix)


@register.function
@jinja2.contextfunction
def hasOneToOne(context, obj, attr):
    try:
        getattr(obj, attr)
        return True
    except ObjectDoesNotExist:
        return False


@register.function
def no_results_amo():
    # This prints a "No results found" message. That's all. Carry on.
    t = get_env().get_template('amo/no_results.html').render()
    return jinja2.Markup(t)


def _relative_to_absolute(url):
    """
    Prepends relative URLs with STATIC_URL to turn those inline-able.
    This method is intended to be used as a ``replace`` parameter of
    ``re.sub``.
    """
    url = url.group(1).strip('"\'')
    if not url.startswith(('data:', 'http:', 'https:', '//')):
        url = url.replace('../../', settings.STATIC_URL)
    return 'url(%s)' % url


@register.function
def inline_css(bundle, media=False, debug=None):
    """
    If we are in debug mode, just output a single style tag for each css file.
    If we are not in debug mode, return a style that contains bundle-min.css.
    Forces a regular css() call for external URLs (no inline allowed).

    Extracted from jingo-minify and re-registered, see:
    https://github.com/jsocol/jingo-minify/pull/41
    Added: turns relative links to absolute ones using STATIC_URL.
    """
    if debug is None:
        debug = getattr(settings, 'TEMPLATE_DEBUG', False)

    if debug:
        items = [_get_compiled_css_url(i)
                 for i in settings.MINIFY_BUNDLES['css'][bundle]]
    else:
        items = ['css/%s-min.css' % bundle]

    if not media:
        media = getattr(settings, 'CSS_MEDIA_DEFAULT', 'screen,projection,tv')

    contents = []
    for css in items:
        if is_external(css):
            return _build_html([css], '<link rel="stylesheet" media="%s" '
                                      'href="%%s" />' % media)
        with open(get_path(css), 'r') as f:
            css_content = f.read()
            css_parsed = re.sub(r'url\(([^)]*?)\)',
                                _relative_to_absolute,
                                css_content)
            contents.append(css_parsed)

    return _build_html(contents, '<style type="text/css" media="%s">%%s'
                                 '</style>' % media)


# A (temporary?) copy of this is in services/utils.py. See bug 1055654.
def user_media_path(what):
    """Make it possible to override storage paths in settings.

    By default, all storage paths are in the MEDIA_ROOT.

    This is backwards compatible.

    """
    default = os.path.join(settings.MEDIA_ROOT, what)
    key = "{0}_PATH".format(what.upper())
    return getattr(settings, key, default)


# A (temporary?) copy of this is in services/utils.py. See bug 1055654.
def user_media_url(what):
    """
    Generate default media url, and make possible to override it from
    settings.
    """
    default = '%s%s/' % (settings.MEDIA_URL, what)
    key = "{0}_URL".format(what.upper().replace('-', '_'))
    return getattr(settings, key, default)


def id_to_path(pk):
    """
    Generate a path from an id, to distribute folders in the file system.
    1 => 1/1/1
    12 => 2/12/12
    123456 => 6/56/123456
    """
    pk = unicode(pk)
    path = [pk[-1]]
    if len(pk) >= 2:
        path.append(pk[-2:])
    else:
        path.append(pk)
    path.append(pk)
    return os.path.join(*path)


@register.filter
def hidden_field(field):
    return field.as_widget(attrs={'style': 'display:none'})
