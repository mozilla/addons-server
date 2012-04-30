from datetime import datetime
import urllib2

from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404

import bleach
from celeryutils import task
import commonware.log
from lxml import etree
from pyquery import PyQuery

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
ALLOWED_ATTRIBUTES['span'] = ['title', ]
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

tutorials = [
    {
        'title': 'Apps Tutorial',
        'name': 'apps',
        'mdn': 'https://developer.mozilla.org/%(locale)s/Apps/Tracks/General'
    },
]

# Instead of duplicating the tutorials entry above for each possible
# locale, we are going to try each locale in this array for each tutorial
# page entry.  We may get some 404s, but that's ok if some translations
# are not finished yet.  We grab the ones that are completed.
locales = ['en']


@task
def refresh_mdn_cache():
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
                toc, content = _fetch_mdn_page(url)
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
            model.toc = toc
            model.content = content
            model.permalink = url
            model.save()

            log.info(u'Updated MDN article "%s"' % name)

    MdnCache.objects.filter(modified__lt=batch_updated).delete()


def _fetch_mdn_page(url):
    data = bleach.clean(_get_page(url), attributes=ALLOWED_ATTRIBUTES,
                        tags=ALLOWED_TAGS, strip_comments=False)

    root = PyQuery(data)
    toc = root.find('#article-nav div.page-toc ol')[0]
    content = root.find('#pageText')[0]

    toc.set('id', 'mdn-toc')
    content.set('id', 'mdn-content')

    return (etree.tostring(toc, pretty_print=True),
        etree.tostring(content, pretty_print=True))


def _get_page(url):
    try:
        return urllib2.urlopen(url).read()
    except URLError as e:
        if e.code == 404:
            raise Http404
        else:
            raise
