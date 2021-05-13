import datetime
import math
import os
from collections import namedtuple
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.sitemaps import Sitemap as DjangoSitemap
from django.db.models import Count, Max, Q
from django.template import loader
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


class Sitemap(DjangoSitemap):
    limit = 1000
    apps = amo.APP_USAGE


class AddonSitemap(Sitemap):
    # i18n = True  # TODO: support all localized urls
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
    # i18n = True  # TODO: support all localized urls
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
            ('contribute.json', None),
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
    # i18n = True  # TODO: support all localized urls
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
    # i18n = True  # TODO: support all localized urls

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
    # i18n = True  # TODO: support all localized urls
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
        # django3.2 adds the xmlns:xhtml namespace in the template
        # we can drop this after we drop support for django2.2
        return xml.replace(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">',
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
