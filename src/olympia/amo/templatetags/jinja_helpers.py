import json as jsonlib
import os
import random

from urllib.parse import urljoin

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.forms import CheckboxInput
from django.template import defaultfilters, Library, loader
from django.utils.encoding import smart_text
from django.utils.html import format_html as django_format_html
from django.utils.safestring import mark_safe
from django.utils.translation import (
    get_language, to_locale, trim_whitespace, ugettext)

import jinja2
import waffle

from babel.support import Format
from django_jinja import library
from rest_framework.reverse import reverse as drf_reverse
from rest_framework.settings import api_settings

from olympia import amo
from olympia.amo import urlresolvers, utils
from olympia.lib.jingo_minify_helpers import (
    _build_html, get_css_urls, get_js_urls)


register = Library()


# Registering some utils as filters:
urlparams = library.filter(utils.urlparams)
library.filter(utils.epoch)
library.filter(utils.isotime)
library.global_function(dict)
library.global_function(utils.randslice)


@library.global_function
def switch_is_active(switch_name):
    return waffle.switch_is_active(switch_name)


@library.filter
def link(item):
    html = """<a href="%s">%s</a>""" % (item.get_url_path(),
                                        jinja2.escape(item.name))
    return jinja2.Markup(html)


@library.filter
def xssafe(value):
    """
    Like |safe but for strings with interpolation.

    By using |xssafe you assert that you have written tests proving an
    XSS can't happen here.
    """
    return jinja2.Markup(value)


@library.global_function
def locale_url(url):
    """Take a URL and give it the locale prefix."""
    prefixer = urlresolvers.get_url_prefix()
    script = prefixer.request.META['SCRIPT_NAME']
    parts = [script, prefixer.locale, url.lstrip('/')]
    return '/'.join(parts)


@library.global_function
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


@library.global_function
@jinja2.contextfunction
def drf_url(context, viewname, *args, **kwargs):
    """Helper for DjangoRestFramework's ``reverse`` in templates."""
    request = context.get('request')
    if request:
        if not hasattr(request, 'versioning_scheme'):
            request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        request.version = request.versioning_scheme.determine_version(
            request, *args, **kwargs)
    return drf_reverse(viewname, request=request, args=args, kwargs=kwargs)


@library.global_function
def services_url(viewname, *args, **kwargs):
    """Helper for ``url`` with host=SERVICES_URL."""
    kwargs.update({'host': settings.SERVICES_URL})
    return url(viewname, *args, **kwargs)


@library.filter
def paginator(pager):
    return PaginationRenderer(pager).render()


@register.filter(needs_autoescape=True)
def dj_paginator(pager, autoescape=True):
    return mark_safe(PaginationRenderer(pager).render())


@library.filter
def impala_paginator(pager):
    t = loader.get_template('amo/impala/paginator.html')
    return jinja2.Markup(t.render({'pager': pager}))


class PaginationRenderer(object):

    def __init__(self, pager):
        self.pager = pager

        self.max = 10
        self.span = (self.max - 1) // 2

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
        t = loader.get_template('amo/paginator.html').render(c)
        return jinja2.Markup(t)


def _get_format():
    lang = get_language()
    return Format(utils.get_locale_from_lang(lang))


@library.filter
def numberfmt(num, format=None):
    return _get_format().decimal(num, format)


@library.global_function
@jinja2.contextfunction
def page_title(context, title):
    title = smart_text(title)
    base_title = ugettext(u'Add-ons for {0}').format(amo.FIREFOX.pretty)
    # The following line doesn't use string formatting because we want to
    # preserve the type of `title` in case it's a jinja2 `Markup` (safe,
    # escaped) object.
    return django_format_html(u'{} :: {}', title, base_title)


@library.filter
def json(s):
    return jsonlib.dumps(s)


@library.filter
def absolutify(url, site=None):
    """Takes a URL and prepends the EXTERNAL_SITE_URL"""
    if url.startswith(('http://', 'http://')):
        return url
    else:
        return urljoin(site or settings.EXTERNAL_SITE_URL, url)


@library.filter
def strip_controls(s):
    """
    Strips control characters from a string.
    """
    # Translation table of control characters.
    control_trans = dict((n, None) for n in range(32) if n not in [10, 13])
    rv = str(s).translate(control_trans)
    return jinja2.Markup(rv) if isinstance(s, jinja2.Markup) else rv


@library.filter
def external_url(url):
    """Bounce a URL off outgoing.prod.mozaws.net."""
    return urlresolvers.get_outgoing_url(str(url))


@library.filter
def shuffle(sequence):
    """Shuffle a sequence."""
    random.shuffle(sequence)
    return sequence


@library.global_function
def field(field, label=None, **attrs):
    if label is not None:
        field.label = label
    # HTML from Django is already escaped.
    return jinja2.Markup(u'%s<p>%s%s</p>' %
                         (field.errors, field.label_tag(),
                          field.as_widget(attrs=attrs)))


@library.global_function
@library.render_with('amo/category-arrow.html')
@jinja2.contextfunction
def category_arrow(context, key, prefix):
    d = dict(context.items())
    d.update(key=key, prefix=prefix)
    return d


@library.filter
def timesince(time):
    if not time:
        return u''
    ago = defaultfilters.timesince(time)
    # L10n: relative time in the past, like '4 days ago'
    return ugettext(u'{0} ago').format(ago)


@library.filter
def timeuntil(time):
    return defaultfilters.timeuntil(time)


@library.global_function
@library.render_with('amo/recaptcha.html')
@jinja2.contextfunction
def recaptcha(context, form):
    d = dict(context.items())
    d.update(form=form)
    return d


@library.filter
def is_choice_field(value):
    try:
        return isinstance(value.field.widget, CheckboxInput)
    except AttributeError:
        pass


@library.global_function
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


@library.global_function
@jinja2.contextfunction
def media(context, url):
    """Get a MEDIA_URL link with a cache buster querystring."""
    return urljoin(settings.MEDIA_URL, cache_buster(context, url))


@library.global_function
@jinja2.contextfunction
def static(context, url):
    """Get a STATIC_URL link with a cache buster querystring."""
    return urljoin(settings.STATIC_URL, cache_buster(context, url))


@library.global_function
@jinja2.evalcontextfunction
def attrs(ctx, *args, **kw):
    return jinja2.filters.do_xmlattr(ctx, dict(*args, **kw))


@library.global_function
def loc(s):
    """A noop function for strings that are not ready to be localized."""
    return trim_whitespace(s)


@library.global_function
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


@library.global_function
@jinja2.contextfunction
def hasOneToOne(context, obj, attr):
    try:
        getattr(obj, attr)
        return True
    except ObjectDoesNotExist:
        return False


@library.global_function
def no_results_amo():
    # This prints a "No results found" message. That's all. Carry on.
    t = loader.get_template('amo/no_results.html').render()
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


@library.filter
def hidden_field(field):
    return field.as_widget(attrs={'style': 'display:none'})


@library.filter
def format_html(string, *args, **kwargs):
    """Uses ``str.format`` for string interpolation.

    Uses ``django.utils.html:format_html`` internally.

    >>> {{ "{0} arguments, {x} arguments"|format_html('args', x='kwargs') }}
    "positional args, kwargs arguments"

    Checks both, *args and **kwargs for potentially unsafe arguments (
    not marked as `mark_safe`) and escapes them appropriately.
    """
    return django_format_html(smart_text(string), *args, **kwargs)


@library.global_function
def js(bundle, debug=None):
    """
    If we are in debug mode, just output a single script tag for each js file.
    If we are not in debug mode, return a script that points at bundle-min.js.

    Copied from jingo-minify until we switch to something better...
    """
    urls = get_js_urls(bundle, debug)
    attrs = ['src="%s"']

    return _build_html(urls, '<script %s></script>' % ' '.join(attrs))


@library.global_function
def css(bundle, media=False, debug=None):
    """
    If we are in debug mode, just output a single script tag for each css file.
    If we are not in debug mode, return a script that points at bundle-min.css.
    """
    urls = get_css_urls(bundle, debug)
    if not media:
        media = getattr(settings, 'CSS_MEDIA_DEFAULT', 'screen,projection,tv')

    return _build_html(urls, '<link rel="stylesheet" media="%s" href="%%s" />'
                             % media)


@library.filter
def nl2br(string):
    """Turn newlines into <br/>."""
    if not string:
        return ''
    return jinja2.Markup('<br/>'.join(jinja2.escape(string).splitlines()))


@library.filter(name='date')
def format_date(value, format='DATE_FORMAT'):
    return defaultfilters.date(value, format)


@library.filter(name='datetime')
def format_datetime(value, format='DATETIME_FORMAT'):
    return defaultfilters.date(value, format)


@library.filter
def class_selected(a, b):
    """Return ``'class="selected"'`` if ``a == b``."""
    return mark_safe('class="selected"' if a == b else '')
