import datetime
import math
import os
from collections import namedtuple
from urllib.parse import urlparse

from django.conf import settings
from django.core import paginator
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import EmptyPage
from django.db.models import Count, Max, Q
from django.template import loader
from django.utils import translation
from django.urls import reverse

from olympia import amo
from olympia.addons.models import Addon, AddonCategory
from olympia.amo.reverse import get_url_prefix, override_url_prefix
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.constants.categories import CATEGORIES
from olympia.bandwagon.models import Collection
from olympia.users.models import UserProfile


# These constants are from:
# https://github.com/mozilla/addons-frontend/blob/master/src/amo/reducers/addonsByAuthors.js
EXTENSIONS_BY_AUTHORS_PAGE_SIZE = 10
THEMES_BY_AUTHORS_PAGE_SIZE = 12
# top 10 locales by visitor from GA (as of May 2021)
FRONTEND_LANGUAGES = [
    'de',
    'en-GB',
    'en-US',
    'es',
    'fr',
    'ja',
    'pl',
    'pt-BR',
    'ru',
    'zh-CN',
]


# Copied over from django because we want the 3.2 version in 2.2.
# We can delete this after we upgrade to django3.2
# https://github.com/django/django/blob/3.2/django/contrib/sitemaps/__init__.py
class DjangoSitemap:
    # This limit is defined by Google. See the index documentation at
    # https://www.sitemaps.org/protocol.html#index.
    limit = 50000

    # If protocol is None, the URLs in the sitemap will use the protocol
    # with which the sitemap was requested.
    protocol = None

    # Enables generating URLs for all languages.
    i18n = False

    # Override list of languages to use.
    languages = None

    # Enables generating alternate/hreflang links.
    alternates = False

    # Add an alternate/hreflang link with value 'x-default'.
    x_default = False

    def _get(self, name, item, default=None):
        try:
            attr = getattr(self, name)
        except AttributeError:
            return default
        if callable(attr):
            if self.i18n:
                # Split the (item, lang_code) tuples again for the location,
                # priority, lastmod and changefreq method calls.
                item, lang_code = item
            return attr(item)
        return attr

    def _languages(self):
        if self.languages is not None:
            return self.languages
        return [lang_code for lang_code, _ in settings.LANGUAGES]

    def _items(self):
        if self.i18n:
            # Create (item, lang_code) tuples for all items and languages.
            # This is necessary to paginate with all languages already considered.
            items = [
                (item, lang_code)
                for lang_code in self._languages()
                for item in self.items()
            ]
            return items
        return self.items()

    def _location(self, item, force_lang_code=None):
        if self.i18n:
            obj, lang_code = item
            # Activate language from item-tuple or forced one before calling location.
            with translation.override(force_lang_code or lang_code):
                return self._get('location', item)
        return self._get('location', item)

    @property
    def paginator(self):
        return paginator.Paginator(self._items(), self.limit)

    def items(self):
        return []

    def location(self, item):
        return item.get_absolute_url()

    def get_protocol(self, protocol=None):
        # Determine protocol
        return self.protocol or protocol or 'http'

    def get_domain(self, site=None):
        # Determine domain
        if site is None:
            if site is None:
                raise ImproperlyConfigured(
                    'To use sitemaps, either enable the sites framework or pass '
                    'a Site/RequestSite object in your view.'
                )
        return site.domain

    def get_urls(self, page=1, site=None, protocol=None):
        protocol = self.get_protocol(protocol)
        domain = self.get_domain(site)
        return self._urls(page, protocol, domain)

    def _urls(self, page, protocol, domain):
        urls = []
        latest_lastmod = None
        all_items_lastmod = True  # track if all items have a lastmod

        paginator_page = self.paginator.page(page)
        for item in paginator_page.object_list:
            loc = f'{protocol}://{domain}{self._location(item)}'
            priority = self._get('priority', item)
            lastmod = self._get('lastmod', item)

            if all_items_lastmod:
                all_items_lastmod = lastmod is not None
                if all_items_lastmod and (
                    latest_lastmod is None or lastmod > latest_lastmod
                ):
                    latest_lastmod = lastmod

            url_info = {
                'item': item,
                'location': loc,
                'lastmod': lastmod,
                'changefreq': self._get('changefreq', item),
                'priority': str(priority if priority is not None else ''),
            }

            if self.i18n and self.alternates:
                alternates = []
                for lang_code in self._languages():
                    loc = f'{protocol}://{domain}{self._location(item, lang_code)}'
                    alternates.append(
                        {
                            'location': loc,
                            'lang_code': lang_code,
                        }
                    )
                if self.x_default:
                    lang_code = settings.LANGUAGE_CODE
                    loc = f'{protocol}://{domain}{self._location(item, lang_code)}'
                    loc = loc.replace(f'/{lang_code}/', '/', 1)
                    alternates.append(
                        {
                            'location': loc,
                            'lang_code': 'x-default',
                        }
                    )
                url_info['alternates'] = alternates

            urls.append(url_info)

        if all_items_lastmod and latest_lastmod:
            self.latest_lastmod = latest_lastmod

        return urls


class Sitemap(DjangoSitemap):
    limit = 1000
    apps = amo.APP_USAGE
    i18n = True
    languages = FRONTEND_LANGUAGES
    alternates = True
    # x_default = False  # TODO: enable this when we can validate it works well

    def _location(self, item, force_lang_code=None):
        if self.i18n:
            obj, lang_code = item
            # modified from Django implementation - we don't rely on locale for urls
            with override_url_prefix(locale=(force_lang_code or lang_code)):
                return self.location(obj)
        return self.location(item)


class AddonSitemap(Sitemap):
    item_tuple = namedtuple(
        'Item', ['last_updated', 'slug', 'urlname', 'page'], defaults=(1,)
    )

    def items(self):
        addons = list(
            Addon.objects.public()
            .order_by('-last_updated')
            .values_list(
                'last_updated',
                'slug',
                'text_ratings_count',
                named=True,
            )
        )
        items = [
            *(
                self.item_tuple(addon.last_updated, addon.slug, 'detail')
                for addon in addons
            ),
            *(
                self.item_tuple(addon.last_updated, addon.slug, 'versions')
                for addon in addons
            ),
        ]
        # add pages for ratings - and extra pages when needed to paginate
        page_size = settings.REST_FRAMEWORK['PAGE_SIZE']
        for addon in addons:
            pages_needed = math.ceil((addon.text_ratings_count or 1) / page_size)
            items.extend(
                self.item_tuple(addon.last_updated, addon.slug, 'ratings.list', page)
                for page in range(1, pages_needed + 1)
            )
        return items

    def lastmod(self, item):
        return item.last_updated

    def location(self, item):
        return reverse(f'addons.{item.urlname}', args=[item.slug]) + (
            f'?page={item.page}' if item.page > 1 else ''
        )


class AMOSitemap(Sitemap):
    lastmod = datetime.datetime.now()
    apps = None  # because some urls are app-less, we specify per item

    def items(self):
        return [
            # frontend pages
            ('home', amo.FIREFOX),
            ('home', amo.ANDROID),
            ('pages.about', None),
            ('pages.review_guide', None),
            ('browse.extensions', amo.FIREFOX),
            ('browse.themes', amo.FIREFOX),
            ('browse.language-tools', amo.FIREFOX),
            # server pages
            ('devhub.index', None),
            ('apps.appversions', amo.FIREFOX),
            ('apps.appversions', amo.ANDROID),
        ]

    def location(self, item):
        urlname, app = item
        if app:
            with override_url_prefix(app_name=app.short):
                return reverse(urlname)
        else:
            return reverse(urlname)


class CategoriesSitemap(Sitemap):
    lastmod = datetime.datetime.now()
    apps = (amo.FIREFOX,)  # category pages aren't supported on android

    def items(self):
        def additems(type):
            items = []
            for category in CATEGORIES[current_app.id][type].values():
                items.append((category, 1))
                pages_needed = math.ceil(addon_counts.get(category.id, 1) / page_size)
                for page in range(2, pages_needed + 1):
                    items.append((category, page))
            return items

        page_size = settings.REST_FRAMEWORK['PAGE_SIZE']
        current_app = amo.APPS[get_url_prefix().get_app()]
        counts_qs = (
            AddonCategory.objects.filter(
                addon___current_version__isnull=False,
                addon___current_version__apps__application=current_app.id,
                addon__disabled_by_user=False,
                addon__status__in=amo.REVIEWED_STATUSES,
            )
            .values('category_id')
            .annotate(count=Count('addon_id'))
        )
        addon_counts = {cat['category_id']: cat['count'] for cat in counts_qs}

        items = additems(amo.ADDON_EXTENSION)
        if current_app == amo.FIREFOX:
            items.extend(additems(amo.ADDON_STATICTHEME))
        return items

    def location(self, item):
        (category, page) = item
        return category.get_url_path() + (f'?page={page}' if page > 1 else '')


class CollectionSitemap(Sitemap):
    def items(self):
        return (
            Collection.objects.filter(author_id=settings.TASK_USER_ID)
            .order_by('-modified')
            .values_list('modified', 'slug', 'author_id', named=True)
        )

    def lastmod(self, item):
        return item.modified

    def location(self, item):
        return Collection.get_url_path(item)


class AccountSitemap(Sitemap):
    item_tuple = namedtuple(
        'AccountItem',
        ['addons_updated', 'id', 'extension_page', 'theme_page'],
        defaults=(1, 1),
    )

    def items(self):
        addon_q = Q(
            addons___current_version__isnull=False,
            addons__disabled_by_user=False,
            addons__status__in=amo.REVIEWED_STATUSES,
            addonuser__listed=True,
            addonuser__role__in=(amo.AUTHOR_ROLE_DEV, amo.AUTHOR_ROLE_OWNER),
        )
        users = (
            UserProfile.objects.filter(is_public=True)
            .annotate(
                theme_count=Count(
                    'addons', filter=Q(addon_q, addons__type=amo.ADDON_STATICTHEME)
                )
            )
            .annotate(
                extension_count=Count(
                    'addons', filter=Q(addon_q, addons__type=amo.ADDON_EXTENSION)
                )
            )
            .annotate(addons_updated=Max('addons__last_updated', filter=addon_q))
            .order_by('-addons_updated', '-modified')
            .values_list(
                'addons_updated', 'id', 'extension_count', 'theme_count', named=True
            )
        )
        items = []
        for user in users:
            extension_pages_needed = math.ceil(
                (user.extension_count or 1) / EXTENSIONS_BY_AUTHORS_PAGE_SIZE
            )
            theme_pages_needed = math.ceil(
                (user.theme_count or 1) / THEMES_BY_AUTHORS_PAGE_SIZE
            )
            items.extend(
                self.item_tuple(user.addons_updated, user.id, ext_page, 1)
                for ext_page in range(1, extension_pages_needed + 1)
            )
            # start themes at 2 because we don't want (1, 1) twice
            items.extend(
                self.item_tuple(user.addons_updated, user.id, 1, theme_page)
                for theme_page in range(2, theme_pages_needed + 1)
            )
        return items

    def lastmod(self, item):
        return item.addons_updated

    def location(self, item):
        urlargs = '&'.join(
            ([f'page_e={item.extension_page}'] if item.extension_page > 1 else [])
            + ([f'page_t={item.theme_page}'] if item.theme_page > 1 else [])
        )
        return UserProfile.create_user_url(item.id) + (f'?{urlargs}' if urlargs else '')


sitemaps = {
    'amo': AMOSitemap(),
    'addons': AddonSitemap(),
    'categories': CategoriesSitemap(),
    'collections': CollectionSitemap(),
    'users': AccountSitemap(),
}


class InvalidSection(Exception):
    pass


def get_sitemap_section_pages():
    pages = []
    for section, site in sitemaps.items():
        if not site.apps:
            pages.extend((section, None, page) for page in site.paginator.page_range)
            continue
        for app in site.apps:
            with override_url_prefix(app_name=app.short):
                # Add all pages of the sitemap section.
                pages.extend(
                    (section, app.short, page) for page in site.paginator.page_range
                )
    return pages


def build_sitemap(section, app_name, page=1):
    if not section:
        # its the index
        if page != 1:
            raise EmptyPage
        sitemap_url = reverse('amo.sitemap')
        urls = (
            f'{sitemap_url}?section={section}'
            + (f'&app_name={app_name}' if app_name else '')
            + (f'&p={page}' if page != 1 else '')
            for section, app_name, page in get_sitemap_section_pages()
        )

        return loader.render_to_string(
            'sitemap_index.xml',
            {'sitemaps': (absolutify(url) for url in urls)},
        )
    else:
        sitemap_object = sitemaps.get(section)
        if not sitemap_object:
            raise InvalidSection
        site_url = urlparse(settings.EXTERNAL_SITE_URL)
        # Sitemap.get_urls wants a Site instance to get the domain, so just fake it.
        site = namedtuple('FakeSite', 'domain')(site_url.netloc)
        with override_url_prefix(app_name=app_name):
            xml = loader.render_to_string(
                'sitemap.xml',
                {
                    'urlset': sitemap_object.get_urls(
                        page=page, site=site, protocol=site_url.scheme
                    )
                },
            )
        return xml


def get_sitemap_path(section, app, page=1):
    return os.path.join(
        settings.SITEMAP_STORAGE_PATH,
        'sitemap'
        + (f'-{section}' if section else '')
        + (f'-{app}' if app else '')
        + (f'-{page}' if page != 1 else '')
        + '.xml',
    )
