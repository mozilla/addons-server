import collections
import os
import logging

from django.conf import settings
from django.db import connection, transaction

from celeryutils import task
import elasticutils

import amo
from amo.decorators import write
from amo.utils import sorted_groupby
from translations.models import Translation
from . import cron, search  # Pull in tasks from cron.
from .forms import get_satisfaction
from .models import Addon, Category, Preview

log = logging.getLogger('z.task')


@task
@write
def version_changed(addon_id, **kw):
    update_last_updated(addon_id)
    update_appsupport([addon_id])


def update_last_updated(addon_id):
    log.info('[1@None] Updating last updated for %s.' % addon_id)
    queries = Addon._last_updated_queries()
    addon = Addon.objects.get(pk=addon_id)
    if addon.is_persona():
        q = 'personas'
    elif addon.status == amo.STATUS_PUBLIC:
        q = 'public'
    elif addon.status == amo.STATUS_LISTED:
        q = 'listed'
    else:
        q = 'exp'
    qs = queries[q].filter(pk=addon_id).using('default')
    pk, t = qs.values_list('id', 'last_updated')[0]
    Addon.objects.filter(pk=pk).update(last_updated=t)


@transaction.commit_on_success
def update_appsupport(ids):
    log.info("[%s@None] Updating appsupport for %s." % (len(ids), ids))
    delete = 'DELETE FROM appsupport WHERE addon_id IN (%s)'
    insert = """INSERT INTO appsupport
                  (addon_id, app_id, min, max, created, modified)
                VALUES %s"""

    addons = Addon.uncached.filter(id__in=ids).no_transforms()
    apps = []
    for addon in addons:
        for app, appver in addon.compatible_apps.items():
            if appver is None:
                # Fake support for all version ranges.
                min_, max_ = 0, 999999999999999999
            else:
                min_, max_ = appver.min.version_int, appver.max.version_int
            apps.append((addon.id, app.id, min_, max_))
    s = ','.join('(%s, %s, %s, %s, NOW(), NOW())' % x for x in apps)

    if not apps:
        return

    cursor = connection.cursor()
    cursor.execute(delete % ','.join(map(str, ids)))
    cursor.execute(insert % s)

    # All our updates were sql, so invalidate manually.
    Addon.objects.invalidate(*addons)


@task
def fix_get_satisfaction(ids, **kw):
    log.info('[%s@None] Fixing get satisfaction starting with id: %s...' %
             (len(ids), ids[0]))
    for addon in Addon.objects.filter(pk__in=ids):
        url = addon.support_url
        if url is None:
            url = ''
        else:
            url = url.localized_string
        (c, p) = get_satisfaction(url)
        addon.update(get_satisfaction_company=c, get_satisfaction_product=p)
        log.info('Updated get satisfaction for: %s' % addon.pk)


@task
def delete_preview_files(id, **kw):
    log.info('[1@None] Removing preview with id of %s.' % id)

    p = Preview(id=id)
    for f in (p.thumbnail_path, p.image_path):
        try:
            os.remove(f)
        except Exception, e:
            log.error('Error deleting preview file (%s): %s' % (f, e))


@task
def index_addons(ids, **kw):
    if not settings.USE_ELASTIC:
        return
    es = elasticutils.get_es()
    log.info('Indexing addons %s-%s. [%s]' % (ids[0], ids[-1], len(ids)))
    qs = (Addon.uncached.filter(id__in=ids).transform(attach_categories)
          .transform(attach_translations))
    for addon in qs:
        Addon.index(search.extract(addon), bulk=True, id=addon.id)
    es.flush_bulk(forced=True)


def attach_categories(addons):
    """Put all of the add-on's categories into a category_ids list."""
    addon_dict = dict((a.id, a) for a in addons)
    categories = (Category.objects.filter(addon__in=addon_dict)
                  .values_list('id', 'addoncategory__addon'))
    for addon, cats in sorted_groupby(categories, lambda x: x[1]):
        addon_dict[addon].category_ids = [c[0] for c in cats]


def attach_translations(addons):
    """Put all translations into a translations dict."""
    fields = Addon._meta.translated_fields
    ids = {}
    for addon in addons:
        addon.translations = collections.defaultdict(list)
        ids.update((getattr(addon, field.attname, None), addon)
                   for field in fields)
    ids.pop(None, None)
    qs = (Translation.objects.filter(id__in=ids, localized_string__isnull=False)
          .values_list('id', 'locale', 'localized_string'))
    for id, translations in sorted_groupby(qs, lambda x: x[0]):
        ids[id].translations[id] = [(locale, string)
                                    for id, locale, string in translations]


@task
def unindex_addons(ids, **kw):
    if not settings.USE_ELASTIC:
        return
    for addon in ids:
        log.info('Removing addon [%s] from search index.' % addon)
        Addon.unindex(addon)
