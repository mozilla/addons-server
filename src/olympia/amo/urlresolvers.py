# -*- coding: utf-8 -*-
import hashlib
import hmac
import re
import urllib

from threading import local

from django.conf import settings
from django.core import urlresolvers
from django.utils.encoding import force_bytes
from django.utils.http import _urlparse as urlparse
from django.utils.translation.trans_real import parse_accept_lang_header

import bleach
import jinja2

from olympia import amo


# Get a pointer to Django's reverse and resolve because we're going to hijack
# them after we define our own.
# As we're using a url prefixer to automatically add the locale and the app to
# URLs, we're not compatible with Django's default reverse and resolve, and
# thus need to monkeypatch them.
django_reverse = urlresolvers.reverse
django_resolve = urlresolvers.resolve


# Thread-local storage for URL prefixes.  Access with {get,set}_url_prefix.
_local = local()


def set_url_prefix(prefix):
    """Set ``prefix`` for the current thread."""
    _local.prefix = prefix


def get_url_prefix():
    """Get the prefix for the current thread, or None."""
    return getattr(_local, 'prefix', None)


def clean_url_prefixes():
    """Purge prefix cache."""
    if hasattr(_local, 'prefix'):
        delattr(_local, 'prefix')


def reverse(viewname, urlconf=None, args=None, kwargs=None, prefix=None,
            current_app=None, add_prefix=True):
    """Wraps django's reverse to prepend the correct locale and app."""
    prefixer = get_url_prefix()
    # Blank out the script prefix since we add that in prefixer.fix().
    if prefixer:
        prefix = prefix or '/'

    url = django_reverse(viewname, urlconf, args, kwargs, prefix, current_app)
    if prefixer and add_prefix:
        return prefixer.fix(url)
    else:
        return url


# Replace Django's reverse with our own.
urlresolvers.reverse = reverse


def resolve(path, urlconf=None):
    """Wraps django's resolve to remove the locale and app from the path."""
    prefixer = get_url_prefix()
    if prefixer:
        _lang, _platform, path_fragment = prefixer.split_path(path)
        path = '/%s' % path_fragment
    return django_resolve(path, urlconf)


# Replace Django's resolve with our own.
urlresolvers.resolve = resolve


class Prefixer(object):

    def __init__(self, request):
        self.request = request
        split = self.split_path(request.path_info)
        self.locale, self.app, self.shortened_path = split

    def split_path(self, path_):
        """
        Split the requested path into (locale, app, remainder).

        locale and app will be empty strings if they're not found.
        """
        path = path_.lstrip('/')

        # Use partition instead of split since it always returns 3 parts.
        first, _, first_rest = path.partition('/')
        second, _, rest = first_rest.partition('/')

        first_lower = first.lower()
        lang, dash, territory = first_lower.partition('-')

        # Check language-territory first.
        if first_lower in settings.LANGUAGES:
            if second in amo.APPS:
                return first, second, rest
            else:
                return first, '', first_rest
        # And check just language next.
        elif dash and lang in settings.LANGUAGES:
            first = lang
            if second in amo.APPS:
                return first, second, rest
            else:
                return first, '', first_rest
        elif first in amo.APPS:
            return '', first, first_rest
        else:
            if second in amo.APPS:
                return '', second, rest
            else:
                return '', '', path

    def get_app(self):
        """
        Return a valid application string using the User Agent to guess.  Falls
        back to settings.DEFAULT_APP.
        """
        ua = self.request.META.get('HTTP_USER_AGENT')
        if ua:
            for app in amo.APP_DETECT:
                if app.matches_user_agent(ua):
                    return app.short

        return settings.DEFAULT_APP

    def get_language(self):
        """
        Return a locale code that we support on the site using the
        user's Accept Language header to determine which is best.  This
        mostly follows the RFCs but read bug 439568 for details.
        """
        data = (self.request.GET or self.request.POST)
        if 'lang' in data:
            lang = data['lang'].lower()
            if lang in settings.LANGUAGE_URL_MAP:
                return settings.LANGUAGE_URL_MAP[lang]
            prefix = lang.split('-')[0]
            if prefix in settings.LANGUAGE_URL_MAP:
                return settings.LANGUAGE_URL_MAP[prefix]

        accept = self.request.META.get('HTTP_ACCEPT_LANGUAGE', '')
        return lang_from_accept_header(accept)

    def fix(self, path):
        path = path.lstrip('/')
        url_parts = [self.request.META['SCRIPT_NAME']]

        if not re.match(settings.SUPPORTED_NONAPPS_NONLOCALES_REGEX, path):
            if path.partition('/')[0] not in settings.SUPPORTED_NONLOCALES:
                url_parts.append(self.locale or self.get_language())

            if path.partition('/')[0] not in settings.SUPPORTED_NONAPPS:
                url_parts.append(self.app or self.get_app())

        url_parts.append(path)
        return '/'.join(url_parts)


def get_outgoing_url(url):
    """
    Bounce a URL off an outgoing URL redirector, such as
    outgoing.prod.mozaws.net.
    """
    if not settings.REDIRECT_URL:
        return url

    parsed_url = urlparse(url)
    url_netloc = parsed_url.netloc

    # This prevents a link like javascript://addons.mozilla.org...
    # being returned unchanged since the netloc matches the
    # safe list see bug 1251023
    if parsed_url.scheme not in ['http', 'https']:
        return '/'

    # No double-escaping, and some domain names are excluded.
    if (url_netloc == urlparse(settings.REDIRECT_URL).netloc or
            url_netloc in settings.REDIRECT_URL_ALLOW_LIST):
        return url

    url = force_bytes(jinja2.utils.Markup(url).unescape())
    sig = hmac.new(settings.REDIRECT_SECRET_KEY,
                   msg=url, digestmod=hashlib.sha256).hexdigest()
    # Let '&=' through so query params aren't escaped.  We probably shouldn't
    # bother to quote the query part at all.
    return '/'.join([settings.REDIRECT_URL.rstrip('/'), sig,
                     urllib.quote(url, safe='/&=')])


def linkify_bounce_url_callback(attrs, new=False):
    """Linkify callback that uses get_outgoing_url."""
    attrs['href'] = get_outgoing_url(attrs['href'])
    return attrs


def linkify_only_full_urls(attrs, new=False):
    """Linkify only full links, containing the scheme."""
    if not new:  # This is an existing <a> tag, leave it be.
        return attrs

    # If the original text doesn't contain the scheme, don't linkify.
    if not attrs['_text'].startswith(('http:', 'https:')):
        return None

    return attrs


# Match HTTP/HTTPS URLs with a valid TLD (not including new gTLDs).
# URLs end at the first occurrence of white space, or certain special
# characters (<>()"'). Full stops and commas are included unless
# they're followed by a space, or the end of the string.
URL_RE = re.compile(r'\bhttps?://([a-z0-9-]+\.)+({0})/'
                    r'([^\s<>()"\x27.,]|[.,](?!\s|$))*'
                    .format('|'.join(bleach.TLDS)))


def linkify_escape(text):
    """Linkifies plain text, escaping any HTML metacharacters already
    present."""
    # Bleach 1.4.1 does a monumentally bad job at this. If we pass it escaped
    # HTML which contains any URLs (&lt;div&gt;http://foo.com/&lt;/div&gt;),
    # we get back HTML (<div><a href="http://foo.com/</div>).
    #
    # So just stick to search-and-replace. We can hardly do a worse job than
    # Bleach does.
    def linkify(match):
        # Parameters are already escaped.
        return u'<a href="{0}">{0}</a>'.format(match.group(0))

    return URL_RE.sub(linkify, unicode(jinja2.escape(text)))


def linkify_with_outgoing(text, nofollow=True, only_full=False):
    """Wrapper around bleach.linkify: uses get_outgoing_url."""
    callbacks = [linkify_only_full_urls] if only_full else []
    callbacks.append(linkify_bounce_url_callback)
    if nofollow:
        callbacks.append(bleach.callbacks.nofollow)
    return bleach.linkify(unicode(text), callbacks=callbacks)


def lang_from_accept_header(header):
    # Map all our lang codes and any prefixes to the locale code.
    langs = dict((k.lower(), v) for k, v in settings.LANGUAGE_URL_MAP.items())

    # If we have a lang or a prefix of the lang, return the locale code.
    for lang, _ in parse_accept_lang_header(header.lower()):
        if lang in langs:
            return langs[lang]

        prefix = lang.split('-')[0]
        # Downgrade a longer prefix to a shorter one if needed (es-PE > es)
        if prefix in langs:
            return langs[prefix]
        # Upgrade to a longer one, if present (zh > zh-CN)
        lookup = settings.SHORTER_LANGUAGES.get(prefix, '').lower()
        if lookup and lookup in langs:
            return langs[lookup]

    return settings.LANGUAGE_CODE
