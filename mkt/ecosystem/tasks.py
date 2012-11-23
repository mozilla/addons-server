from datetime import datetime
import urllib2

from django.http import Http404

import bleach
from celeryutils import task
import commonware.log
from pyquery import PyQuery as pq

from models import MdnCache


log = commonware.log.getLogger('z.ecosystem.task')


ALLOWED_TAGS = bleach.ALLOWED_TAGS + [
    'div', 'span', 'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'pre', 'code',
    'dl', 'dt', 'dd', 'small', 'sup', 'u',
    'img',
    'input',
    'table', 'tbody', 'thead', 'tr', 'th', 'td',
    'section', 'header', 'footer', 'nav', 'article', 'aside', 'figure',
    'dialog', 'hgroup', 'mark', 'time', 'meter', 'command', 'output',
    'progress', 'audio', 'video', 'details', 'datagrid', 'datalist', 'table',
    'address'
]
ALLOWED_ATTRIBUTES = bleach.ALLOWED_ATTRIBUTES
ALLOWED_ATTRIBUTES['div'] = ['class', 'id']
ALLOWED_ATTRIBUTES['p'] = ['class', 'id']
ALLOWED_ATTRIBUTES['pre'] = ['class', 'id']
ALLOWED_ATTRIBUTES['span'] = ['title', 'id']
ALLOWED_ATTRIBUTES['img'] = ['src', 'id', 'align', 'alt', 'class', 'is',
                             'title', 'style']
ALLOWED_ATTRIBUTES['a'] = ['id', 'class', 'href', 'title', ]
ALLOWED_ATTRIBUTES.update(dict((x, ['name', ]) for x in
                          ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')))
ALLOWED_ATTRIBUTES.update(dict((x, ['id', ]) for x in (
    'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'code', 'dl', 'dt', 'dd',
    'section', 'header', 'footer', 'nav', 'article', 'aside', 'figure',
    'dialog', 'hgroup', 'mark', 'time', 'meter', 'command', 'output',
    'progress', 'audio', 'video', 'details', 'datagrid', 'datalist', 'table',
    'address'
)))
VIDEO_HEIGHT = 360
VIDEO_WIDTH = 640

tutorials = [
    {
        'title': 'Foundations of an HTML5 Web app',
        'name': 'html5',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/Tutorials/General/Foundations_of_an_HTML5_Web_app?raw=1&macros=true'
    },
    {
        'title': 'Manifests',
        'name': 'manifests',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/Manifest?raw=1&macros=true'
    },
    {
        'title': 'Manifest FAQ',
        'name': 'manifest_faq',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/FAQs/About_app_manifests?raw=1&macros=true'
    },
    {
        'title': 'Firefox OS',
        'name': 'firefox_os',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Mozilla/Boot_to_Gecko?raw=1&macros=true'
    },
    {
        'title': 'Marketplace Submission',
        'name': 'mkt_submission',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/Submitting_an_app?raw=1&macros=true'
    },
    {
        'title': 'Hosting',
        'name': 'mkt_hosting',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/Tutorials/General/Publishing_the_app?raw=1&macros=true'
    },
    {
        'title': 'Design Principles',
        'name': 'principles',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/Design_Guidelines/Design_Principles?raw=1&macros=true'
    },
    {
        'title': "Your App's Elevator Pitch",
        'name': 'purpose',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/Design_Guidelines/Your_apps_elevator_pitch?raw=1&macros=true'
    },
    {
        'title': 'Design Patterns',
        'name': 'patterns',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/Design_Guidelines/Intro_to_responsive_design?raw=1&macros=true'
    },
    {
        'title': 'References',
        'name': 'references',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/Design_Guidelines/References?raw=1&macros=true'
    },
    {
        'title': 'Dev Tools',
        'name': 'devtools',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/marketplace/App_developer_tools?raw=1&macros=true'
    },
    {
        'title': 'App Templates',
        'name': 'templates',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/App_templates?raw=1&macros=true'
    },
    {
        'title': 'Custom Elements',
        'name': 'custom_elements',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/Custom_Elements?raw=1&macros=true'
    },
    {
        'title': 'Packaged Apps',
        'name': 'packaged_apps',
        'mdn': 'https://developer.mozilla.org/%(locale)s/docs/Apps/Packaged_apps?raw=1&macros=true'
    }
]

# Instead of duplicating the tutorials entry above for each possible
# locale, we are going to try each locale in this array for each tutorial
# page entry.  We may get some 404s, but that's ok if some translations
# are not finished yet.  We grab the ones that are completed.
locales = ['en-US']


@task
def refresh_mdn_cache(**kw):
    log.info('Refreshing MDN Cache')
    try:
        _update_mdn_items(tutorials)
    except Exception as e:
        log.error(u'Failed to update MDN articles, reason: %s' % e,
            exc_info=True)


def _update_mdn_items(items):
    batch_updated = datetime.now()
    for item in items:
        for locale in locales:

            url = item['mdn'] % {'locale': locale}
            name = item['name'] + '.' + locale

            log.info('Fetching MDN article "%s": %s' % (name, url))

            try:
                content = _fetch_mdn_page(url)
            except Http404:
                log.error(u'404 on MDN article "%s": %s' % (name, url))
                continue
            except Exception as e:
                log.error(u'Error fetching MDN article "%s" reason: %s' %
                    (name, e))
                raise

            model, created = MdnCache.objects.get_or_create(
                name=item['name'], locale=locale)

            model.title = item['title']
            model.content = content
            model.permalink = url
            model.save()

            log.info(u'Updated MDN article "%s"' % name)

    MdnCache.objects.filter(modified__lt=batch_updated).delete()


def _fetch_mdn_page(url):
    data = bleach.clean(_get_page(url), attributes=ALLOWED_ATTRIBUTES,
                        tags=ALLOWED_TAGS, strip_comments=False)

    root = pq(data)
    anchors = root.find('a')
    videos = root.find('.video-item')
    images = root.find('img')
    video_frame = ('<iframe frameborder="0" width="%d" '
                   'height="%d" src="%s">%s</iframe>')

    if anchors:
        # We only want anchors that have an href attribute available.
        external_links = anchors.filter(lambda i: pq(this).attr('href'))
        for link in external_links:
            link = pq(link)
            if link.hasClass('external') or link.attr('rel') == 'external':
                link.attr('target', '_blank')
                link.attr('rel', 'external')
        # PyQuery doesn't like the idea of filtering like
        # external_links.filter('a[href^="/"'), so we'll just do as they
        # suggest for now.
        mdn_links = external_links.filter(
            lambda i: str(pq(this).attr('href')).startswith('/')
        )
        mdn_links.each(lambda e: e.attr(
            'href', 'https://developer.mozilla.org%s' % e.attr('href'))
        )

    if images:
        image_links = images.filter(
            lambda i: str(pq(this).attr('src')).startswith('/')
        )
        image_links.each(lambda e: e.attr(
            'src', 'https://developer.mozilla.org%s' % e.attr('src'))
        )

    for video in videos:
        video = pq(video)
        video.replaceWith(pq(video_frame % (VIDEO_WIDTH,
                                            VIDEO_HEIGHT,
                                            video.attr('href'),
                                            video.attr('href')))
        )

    return str(root)


def _get_page(url):
    try:
        return urllib2.urlopen(url).read()
    except urllib2.URLError as e:
        if e.code == 404:
            raise Http404
        else:
            raise
