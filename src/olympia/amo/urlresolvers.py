import hashlib
import hmac
import re
from urllib.parse import quote, urlparse

from django.conf import settings
from django.utils.encoding import force_bytes
from django.utils.translation.trans_real import parse_accept_lang_header

import markupsafe
from justhtml import (
    Edit,
    JustHTML,
    Linkify,
    SanitizationPolicy,
    Sanitize,
    SetAttrs,
    UrlPolicy,
    UrlRule,
)

from olympia import amo


class Prefixer:
    def __init__(self, request):
        self.request = request
        split = self.split_path(request.path_info)
        self.locale, self.app, self.shortened_path = split

    @staticmethod
    def split_path(path_):
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

        # First test shorter languages shortcuts.
        if not dash and first in settings.SHORTER_LANGUAGES:
            first_short = settings.SHORTER_LANGUAGES[first]
            if second in amo.APPS:
                return first_short, second, rest
            else:
                return first_short, '', first_rest
        # Then check language-territory.
        elif first_lower in settings.LANGUAGE_URL_MAP:
            if second in amo.APPS:
                return first, second, rest
            else:
                return first, '', first_rest
        # And check just language next.
        elif dash and lang in settings.LANGUAGE_URL_MAP:
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
        Return a valid application string based on the `app` query parameter or
        the User Agent. Falls back to settings.DEFAULT_APP.
        """
        if 'app' in self.request.GET:
            app = self.request.GET['app'].lower()
            if app in amo.APPS.keys():
                return app

        ua = self.request.META.get('HTTP_USER_AGENT')
        if ua:
            for app in amo.APP_DETECT:
                if app.matches_user_agent(ua):
                    return app.short

        return settings.DEFAULT_APP

    def get_language(self):
        """
        Return a locale code that we support on the site using `lang` from GET,
        falling back to the user's Accept Language header if necessary (mostly
        following the RFCs but read bug 439568 for details).
        """
        if 'lang' in self.request.GET:
            lang = self.request.GET['lang'].lower()
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
    allowed = settings.REDIRECT_URL_ALLOW_LIST + [
        urlparse(settings.EXTERNAL_SITE_URL).netloc
    ]
    if url_netloc == urlparse(settings.REDIRECT_URL).netloc or url_netloc in allowed:
        return url

    url = force_bytes(markupsafe.Markup(url).unescape())
    sig = hmac.new(
        force_bytes(settings.REDIRECT_SECRET_KEY), msg=url, digestmod=hashlib.sha256
    ).hexdigest()
    # Let '&=' through so query params aren't escaped.  We probably shouldn't
    # bother to quote the query part at all.
    return '/'.join([settings.REDIRECT_URL.rstrip('/'), sig, quote(url, safe='/&=')])


def linkify_bounce_url_callback(node):
    """Linkify callback that uses get_outgoing_url."""
    if 'href' in node.attrs.keys():
        node.attrs['href'] = get_outgoing_url(node.attrs['href'])


def linkify_with_outgoing(text):
    """Wrapper around justhtml's linkify: uses get_outgoing_url."""
    fragment = JustHTML(
        text,
        fragment=True,
        sanitize=False,
        transforms=[
            Linkify(),
            Edit('a', linkify_bounce_url_callback),
            SetAttrs('a', rel='nofollow'),
        ],
    )
    return fragment.to_html(pretty=False)


def linkify_and_clean(text):
    fragment = JustHTML(
        text,
        fragment=True,
        transforms=[
            Sanitize(
                policy=SanitizationPolicy(
                    allowed_tags={'a'},
                    allowed_attributes={'a': ['href']},
                    disallowed_tag_handling='escape',
                    url_policy=UrlPolicy(
                        allow_rules={
                            ('a', 'href'): UrlRule(
                                allowed_schemes=['http', 'https'],
                                handling='allow',
                            )
                        },
                    ),
                )
            ),
            Linkify(extra_tlds={'http:', 'https:'}),
            SetAttrs('a', rel='nofollow'),
        ],
    )
    return fragment.to_html(pretty=False)


def lang_from_accept_header(header):
    # Map all our lang codes and any prefixes to the locale code.
    langs = settings.LANGUAGE_URL_MAP

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
