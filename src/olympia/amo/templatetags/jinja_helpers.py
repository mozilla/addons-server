import json as jsonlib
import os

from urllib.parse import urljoin

from django.conf import settings
from django.forms import CheckboxInput
from django.template import defaultfilters, Library, loader
from django.templatetags.static import static
from django.urls import reverse
from django.utils.encoding import smart_str
from django.utils.html import (
    format_html as django_format_html,
    strip_spaces_between_tags,
)
from django.utils.safestring import mark_safe
from django.utils.translation import get_language, gettext

import jinja2
import markupsafe
import waffle
from jinja2.ext import Extension

from babel.support import Format
from django_jinja import library
from rest_framework.reverse import reverse as drf_reverse
from rest_framework.settings import api_settings

from olympia import amo
from olympia.amo import urlresolvers, utils
from olympia.amo.reverse import get_url_prefix
from olympia.lib.jingo_minify_helpers import _build_html, get_css_urls, get_js_urls


register = Library()


# Registering some utils as filters:
library.filter(utils.isotime)
library.global_function(dict)
library.global_function(static)


@library.filter
def urlparams(*args, **kwargs):
    return markupsafe.Markup(utils.urlparams(*args, **kwargs))


@library.global_function
def switch_is_active(switch_name):
    return waffle.switch_is_active(switch_name)


@library.global_function
def locale_url(url):
    """Take a URL and give it the locale prefix."""
    prefixer = get_url_prefix()
    script = prefixer.request.META['SCRIPT_NAME']
    parts = [script, prefixer.locale, url.lstrip('/')]
    return '/'.join(parts)


@library.global_function
def url(viewname, *args, **kwargs):
    """Helper for Django's ``reverse`` in templates."""
    add_prefix = kwargs.pop('add_prefix', True)
    host = kwargs.pop('host', '')
    url = '{}{}'.format(
        host,
        reverse(viewname, args=args, kwargs=kwargs, add_prefix=add_prefix),
    )
    return url


@library.global_function
@jinja2.pass_context
def drf_url(context, viewname, *args, **kwargs):
    """Helper for DjangoRestFramework's ``reverse`` in templates."""
    request = context.get('request')
    if request:
        if not hasattr(request, 'versioning_scheme'):
            request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        request.version = request.versioning_scheme.determine_version(
            request, *args, **kwargs
        )
    return drf_reverse(viewname, request=request, args=args, kwargs=kwargs)


@library.filter
def paginator(pager):
    return PaginationRenderer(pager).render()


@register.filter(needs_autoescape=True)
def dj_paginator(pager, autoescape=True):
    return mark_safe(PaginationRenderer(pager).render())


@library.filter
def impala_paginator(pager):
    t = loader.get_template('amo/impala/paginator.html')
    return markupsafe.Markup(t.render({'pager': pager}))


class PaginationRenderer:
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
        c = {'pager': self.pager, 'num_pages': self.num_pages, 'count': self.count}
        t = loader.get_template('amo/paginator.html').render(c)
        return markupsafe.Markup(t)


def _get_format():
    lang = get_language()
    return Format(utils.get_locale_from_lang(lang))


@library.filter
def numberfmt(num, format=None):
    return _get_format().decimal(num, format)


@library.global_function
@jinja2.pass_context
def page_title(context, title):
    title = smart_str(title)
    base_title = gettext('Add-ons for {0}').format(amo.FIREFOX.pretty)
    # The following line doesn't use string formatting because we want to
    # preserve the type of `title` in case it's a jinja2 `Markup` (safe,
    # escaped) object.
    return django_format_html('{} :: {}', title, base_title)


@library.filter
def json(s):
    return jsonlib.dumps(s)


@library.filter
def absolutify(url, site=None):
    """Take an URL and prepend the EXTERNAL_SITE_URL."""
    if url and url.startswith(('http://', 'https://')):
        return url

    return urljoin(site or settings.EXTERNAL_SITE_URL, url)


@library.filter
def external_url(url):
    """Bounce a URL off outgoing.prod.mozaws.net."""
    return urlresolvers.get_outgoing_url(str(url))


@library.filter
def timesince(time):
    if not time:
        return ''
    ago = defaultfilters.timesince(time)
    # L10n: relative time in the past, like '4 days ago'
    return gettext('{0} ago').format(ago)


@library.filter
def timeuntil(time):
    return defaultfilters.timeuntil(time)


@library.filter
def is_choice_field(value):
    try:
        return isinstance(value.field.widget, CheckboxInput)
    except AttributeError:
        pass


# A (temporary?) copy of this is in services/utils.py. See bug 1055654.
def user_media_path(what):
    """Make it possible to override storage paths in settings.

    By default, all storage paths are in the MEDIA_ROOT.

    This is backwards compatible.

    """
    default = os.path.join(settings.MEDIA_ROOT, what)
    key = f'{what.upper()}_PATH'
    return getattr(settings, key, default)


# A (temporary?) copy of this is in services/utils.py. See bug 1055654.
def user_media_url(what):
    """
    Generate default media url, and make possible to override it from
    settings.
    """
    default = f'{settings.MEDIA_URL}{what}/'
    key = '{}_URL'.format(what.upper().replace('-', '_'))
    return getattr(settings, key, default)


@library.filter
def format_html(string, *args, **kwargs):
    """Uses ``str.format`` for string interpolation.

    Uses ``django.utils.html:format_html`` internally.

    >>> {{ "{0} arguments, {x} arguments"|format_html('args', x='kwargs') }}
    "positional args, kwargs arguments"

    Checks both, *args and **kwargs for potentially unsafe arguments (
    not marked as `mark_safe`) and escapes them appropriately.
    """
    return django_format_html(smart_str(string), *args, **kwargs)


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
        media = 'all'

    return _build_html(urls, '<link rel="stylesheet" media="%s" href="%%s" />' % media)


@library.filter
def nl2br(string):
    """Turn newlines into <br/>."""
    if not string:
        return ''
    return markupsafe.Markup('<br/>'.join(markupsafe.escape(string).splitlines()))


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


class Spaceless(Extension):
    tags = {'spaceless'}

    def parse(self, parser):
        lineno = next(parser.stream).lineno
        body = parser.parse_statements(['name:endspaceless'], drop_needle=True)
        return jinja2.nodes.CallBlock(
            self.call_method('_strip_spaces'),
            [],
            [],
            body,
        ).set_lineno(lineno)

    def _strip_spaces(self, *, caller):
        return strip_spaces_between_tags(caller().strip())


def new_context(context, **kw):
    c = dict(context.items())
    c.update(kw)
    return c
