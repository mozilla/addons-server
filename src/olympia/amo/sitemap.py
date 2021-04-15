import datetime
import os
from collections import namedtuple
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.template import loader
from django.urls import reverse

from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.bandwagon.models import Collection


class AddonSitemap(Sitemap):
    priority = 1
    changefreq = 'daily'
    # i18n = True  # TODO: support all localized urls

    def items(self):
        return (
            Addon.objects.public()
            .order_by('last_updated')
            .values_list('last_updated', 'slug', named=True)
        )

    def lastmod(self, item):
        return item.last_updated

    def location(self, item):
        return reverse('addons.detail', args=[item.slug])


class AMOSitemap(Sitemap):
    priority = 0.7
    # i18n = True  # TODO: support all localized urls
    changefreq = 'always'
    lastmod = datetime.datetime.now()

    def items(self):
        return [
            'pages.about',
            'contribute.json',
            'devhub.index',
            'pages.review_guide',
            'apps.appversions',
            'apps.appversions.rss',
        ]

    def location(self, item):
        return reverse(item)


class CollectionSitemap(Sitemap):
    priority = 0.5
    changefreq = 'daily'
    # i18n = True  # TODO: support all localized urls

    def items(self):
        return (
            Collection.objects.filter(author_id=settings.TASK_USER_ID)
            .order_by('modified')
            .values_list('modified', 'slug', 'author_id', named=True)
        )

    def lastmod(self, item):
        return item.modified

    def location(self, item):
        return Collection.get_url_path(item)


sitemaps = {
    'amo': AMOSitemap(),
    'addons': AddonSitemap(),
    'collections': CollectionSitemap(),
}


def get_sitemap_section_pages():
    pages = []
    for section, site in sitemaps.items():
        pages.append((section, 1))
        # Add all pages of the sitemap section.
        for page in range(2, site.paginator.num_pages + 1):
            pages.append((section, page))
    return pages


def build_sitemap(section=None, page=1):
    if not section:
        # its the index
        sitemap_url = reverse('amo.sitemap')
        urls = (
            f'{sitemap_url}?section={section}' + ('' if page == 1 else f'&p={page}')
            for section, page in get_sitemap_section_pages()
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


def get_sitemap_path(section=None, page=1):
    return os.path.join(
        settings.SITEMAP_STORAGE_PATH,
        'sitemap'
        + (f'-{section}' if section else '')
        + ('' if page == 1 else f'-{page}')
        + '.xml',
    )
