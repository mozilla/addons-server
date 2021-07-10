import datetime
import math
import os
from collections import namedtuple
from urllib.parse import urlparse

from django.conf import settings
from django.core import paginator
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Count, Max, Q
from django.template import loader
from django.utils import translation
from django.utils.functional import cached_property
from django.urls import reverse

from olympia import amo
from olympia.addons.models import Addon, AddonCategory
from olympia.amo.reverse import get_url_prefix, override_url_prefix
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.constants.categories import CATEGORIES
from olympia.constants.promoted import RECOMMENDED
from olympia.bandwagon.models import Collection
from olympia.promoted.models import PromotedAddon
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


class LazyTupleList:
    """Lazily emulates a generated list like:
    [
        (item_a, item_b)
        for item_b in list_b
        for item_a in list_a
    ]
    """

    def __init__(self, list_a, list_b):
        self.list_a = list_a
        self.list_b = list_b

    def __len__(self):
        return len(self.list_a) * len(self.list_b)

    def __getitem__(self, key):
        a_len = len(self.list_a)

        def get(index):
            return (self.list_a[index % a_len], self.list_b[index // a_len])

        return (
            [get(idx) for idx in range(key.start, key.stop, key.step or 1)]
            if isinstance(key, slice)
            else get(key)
        )


class Sitemap(DjangoSitemap):
    limit = 2000
    i18n = True
    languages = FRONTEND_LANGUAGES
    alternates = True
    # x_default = False  # TODO: enable this when we can validate it works well
    _cached_items = []
    protocol = urlparse(settings.EXTERNAL_SITE_URL).scheme

    def _location(self, item, force_lang_code=None):
        # modified from Django implementation - we don't rely on locale for urls
        if self.i18n:
            obj, lang_code = item
            # Doing .replace is hacky, but `override_url_prefix` is slow at scale
            return self.location(obj).replace(
                settings.LANGUAGE_CODE, force_lang_code or lang_code, 1
            )
        return self.location(item)

    def _items(self):
        items = self.items()
        if self.i18n:
            # Create (item, lang_code) tuples for all items and languages.
            # This is necessary to paginate with all languages already considered.
            return LazyTupleList(items, self._languages())
        return items

    def items(self):
        return self._cached_items

    def get_domain(self, site):
        if not site:
            if not hasattr(self, 'domain'):
                self.domain = urlparse(settings.EXTERNAL_SITE_URL).netloc
            return self.domain
        return super().get_domain(site=site)

    def get_urls(self, page=1, site=None, protocol=None, *, app_name=None):
        with override_url_prefix(app_name=app_name):
            return super().get_urls(page=page, site=site, protocol=protocol)

    @cached_property
    def template(self):
        return loader.get_template('sitemap.xml')

    def render(self, app_name, page):
        context = {'urlset': self.get_urls(page=page, app_name=app_name)}
        return self.template.render(context)

    @property
    def _current_app(self):
        return amo.APPS[get_url_prefix().app]


def get_android_promoted_addons():
    return PromotedAddon.objects.filter(
        Q(application_id=amo.ANDROID.id) | Q(application_id__isnull=True),
        group_id=RECOMMENDED.id,
        addon___current_version__promoted_approvals__application_id=(amo.ANDROID.id),
        addon___current_version__promoted_approvals__group_id=RECOMMENDED.id,
    )


class AddonSitemap(Sitemap):
    item_tuple = namedtuple('Item', ['last_updated', 'url', 'page'], defaults=(1,))

    @cached_property
    def _cached_items(self):
        current_app = self._current_app
        addons_qs = Addon.objects.public().filter(
            _current_version__apps__application=current_app.id
        )

        # android is currently limited to a small number of recommended addons, so get
        # the list of those and filter further
        if current_app == amo.ANDROID:
            promoted_addon_ids = get_android_promoted_addons().values_list(
                'addon_id', flat=True
            )
            addons_qs = addons_qs.filter(id__in=promoted_addon_ids)
        addons = list(
            addons_qs.order_by('-last_updated')
            .values_list(
                'last_updated',
                'slug',
                'text_ratings_count',
                named=True,
            )
            .iterator()
        )
        items = [
            self.item_tuple(
                addon.last_updated,
                reverse('addons.detail', args=[addon.slug]),
            )
            for addon in addons
        ]
        # add pages for ratings - and extra pages when needed to paginate
        page_size = settings.REST_FRAMEWORK['PAGE_SIZE']
        for addon in addons:
            pages_needed = math.ceil((addon.text_ratings_count or 1) / page_size)
            items.extend(
                self.item_tuple(
                    addon.last_updated,
                    reverse('addons.ratings.list', args=[addon.slug]),
                    page,
                )
                for page in range(1, pages_needed + 1)
            )
        return items

    def lastmod(self, item):
        return item.last_updated

    def location(self, item):
        return item.url + (f'?page={item.page}' if item.page > 1 else '')


class AMOSitemap(Sitemap):
    lastmod = datetime.datetime.now()

    _cached_items = [
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

    @cached_property
    def _cached_items(self):
        page_size = settings.REST_FRAMEWORK['PAGE_SIZE']
        page_count_max = settings.ES_MAX_RESULT_WINDOW // page_size

        def additems(type):
            items = []
            for category in CATEGORIES[current_app.id][type].values():
                items.append((category, 1))
                pages_needed = min(
                    math.ceil(addon_counts.get(category.id, 1) / page_size),
                    page_count_max,
                )
                for page in range(2, pages_needed + 1):
                    items.append((category, page))
            return items

        current_app = self._current_app
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
    @cached_property
    def _cached_items(self):
        return list(
            Collection.objects.filter(author_id=settings.TASK_USER_ID)
            .order_by('-modified')
            .values_list('modified', 'slug', 'author_id', named=True)
            .iterator()
        )

    def lastmod(self, item):
        return item.modified

    def location(self, item):
        return Collection.get_url_path(item)


class AccountSitemap(Sitemap):
    item_tuple = namedtuple(
        'AccountItem',
        ['addons_updated', 'url', 'extension_page', 'theme_page'],
        defaults=(1, 1),
    )

    @cached_property
    def _cached_items(self):
        current_app = self._current_app
        addon_q = Q(
            addons___current_version__isnull=False,
            addons___current_version__apps__application=current_app.id,
            addons__disabled_by_user=False,
            addons__status__in=amo.REVIEWED_STATUSES,
            addonuser__listed=True,
            addonuser__role__in=(amo.AUTHOR_ROLE_DEV, amo.AUTHOR_ROLE_OWNER),
        )
        # android is currently limited to a small number of recommended addons, so get
        # the list of those and filter further
        if current_app == amo.ANDROID:
            promoted_addon_ids = get_android_promoted_addons().values_list(
                'addon_id', flat=True
            )
            addon_q = addon_q & Q(addons__id__in=promoted_addon_ids)

        users = (
            UserProfile.objects.filter(is_public=True, deleted=False)
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
            .iterator()
        )
        items = []
        for user in users:
            if not user.extension_count and not user.theme_count:
                # some users have an empty page for various reasons, no need to include
                continue
            extension_pages_needed = math.ceil(
                (user.extension_count or 1) / EXTENSIONS_BY_AUTHORS_PAGE_SIZE
            )
            theme_pages_needed = math.ceil(
                (user.theme_count or 1) / THEMES_BY_AUTHORS_PAGE_SIZE
            )
            items.extend(
                self.item_tuple(
                    user.addons_updated,
                    reverse('users.profile', args=[user.id]),
                    ext_page,
                    1,
                )
                for ext_page in range(1, extension_pages_needed + 1)
            )
            # start themes at 2 because we don't want (1, 1) twice
            items.extend(
                self.item_tuple(
                    user.addons_updated,
                    reverse('users.profile', args=[user.id]),
                    1,
                    theme_page,
                )
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
        return item.url + (f'?{urlargs}' if urlargs else '')


def get_sitemaps():
    return {
        # because some urls are app-less, we specify per item, so don't specify an app
        ('amo', None): AMOSitemap(),
        ('addons', amo.FIREFOX): AddonSitemap(),
        ('addons', amo.ANDROID): AddonSitemap(),
        # category pages aren't supported on android, so firefox only
        ('categories', amo.FIREFOX): CategoriesSitemap(),
        # we don't expose collections on android, so firefox only
        ('collections', amo.FIREFOX): CollectionSitemap(),
        ('users', amo.FIREFOX): AccountSitemap(),
        ('users', amo.ANDROID): AccountSitemap(),
    }


OTHER_SITEMAPS = [
    '/blog/sitemap.xml',
]


def get_sitemap_section_pages(sitemaps):
    pages = []
    for (section, app), site in sitemaps.items():
        if not app:
            pages.extend((section, None, page) for page in site.paginator.page_range)
            continue
        with override_url_prefix(app_name=app.short):
            # Add all pages of the sitemap section.
            pages.extend(
                (section, app.short, page) for page in site.paginator.page_range
            )
    return pages


def render_index_xml(sitemaps):
    sitemap_url = reverse('amo.sitemap')
    server_urls = (
        f'{sitemap_url}?section={section}'
        + (f'&app_name={app_name}' if app_name else '')
        + (f'&p={page}' if page != 1 else '')
        for section, app_name, page in get_sitemap_section_pages(sitemaps)
    )
    urls = list(server_urls) + OTHER_SITEMAPS

    return loader.render_to_string(
        'sitemap_index.xml',
        {'sitemaps': (absolutify(url) for url in urls)},
    )


def get_sitemap_path(section, app, page=1):
    return os.path.join(
        settings.SITEMAP_STORAGE_PATH,
        'sitemap'
        + (f'-{section}' if section else '')
        + (f'-{app}' if app else '')
        + (f'-{page}' if page != 1 else '')
        + '.xml',
    )
