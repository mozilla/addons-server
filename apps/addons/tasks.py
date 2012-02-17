import os
import logging

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import connection, transaction

from celeryutils import task
import elasticutils
from PIL import Image

import amo
from amo.decorators import set_modified_on, write
from amo.utils import attach_trans_dict, sorted_groupby
from market.models import AddonPremium
from tags.models import Tag
from versions.models import Version
from . import cron, search  # Pull in tasks from cron.
from .models import (Addon, Category, CompatOverride, DeviceType,
                     IncompatibleVersions, Preview)

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
    res = qs.values_list('id', 'last_updated')
    if res:
        pk, t = res[0]
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
def delete_preview_files(id, **kw):
    log.info('[1@None] Removing preview with id of %s.' % id)

    p = Preview(id=id)
    for f in (p.thumbnail_path, p.image_path):
        try:
            storage.delete(f)
        except Exception, e:
            log.error('Error deleting preview file (%s): %s' % (f, e))


@task
def index_addons(ids, **kw):
    es = elasticutils.get_es()
    log.info('Indexing addons %s-%s. [%s]' % (ids[0], ids[-1], len(ids)))
    qs = Addon.uncached.filter(id__in=ids)
    transforms = (attach_categories, attach_devices, attach_prices,
                  attach_tags, attach_translations)
    for t in transforms:
        qs = qs.transform(t)
    for addon in qs:
        Addon.index(search.extract(addon), bulk=True, id=addon.id)
    es.flush_bulk(forced=True)


def attach_devices(addons):
    addon_dict = dict((a.id, a) for a in addons if a.type == amo.ADDON_WEBAPP)
    devices = (DeviceType.objects.filter(addondevicetype__addon__in=addon_dict)
               .values_list('addondevicetype__addon', 'id'))
    for addon, device_types in sorted_groupby(devices, lambda x: x[0]):
        addon_dict[addon].device_ids = [d[1] for d in device_types]


def attach_prices(addons):
    addon_dict = dict((a.id, a) for a in addons)
    prices = (AddonPremium.objects
              .filter(addon__in=addon_dict,
                      addon__premium_type__in=amo.ADDON_PREMIUMS)
              .values_list('addon', 'price__price'))
    for addon, price in prices:
        addon_dict[addon].price = price


def attach_categories(addons):
    """Put all of the add-on's categories into a category_ids list."""
    addon_dict = dict((a.id, a) for a in addons)
    categories = (Category.objects.filter(addoncategory__addon__in=addon_dict)
                  .values_list('addoncategory__addon', 'id'))
    for addon, cats in sorted_groupby(categories, lambda x: x[0]):
        addon_dict[addon].category_ids = [c[1] for c in cats]


def attach_translations(addons):
    """Put all translations into a translations dict."""
    attach_trans_dict(Addon, addons)


def attach_tags(addons):
    addon_dict = dict((a.id, a) for a in addons)
    qs = (Tag.objects.not_blacklisted().filter(addons__in=addon_dict)
          .values_list('addons__id', 'tag_text'))
    for addon, tags in sorted_groupby(qs, lambda x: x[0]):
        addon_dict[addon].tag_list = [t[1] for t in tags]


@task
def unindex_addons(ids, **kw):
    for addon in ids:
        log.info('Removing addon [%s] from search index.' % addon)
        Addon.unindex(addon)


@task
def delete_persona_image(dst, **kw):
    log.info('[1@None] Deleting persona image: %s.' % dst)
    if not dst.startswith(settings.PERSONAS_PATH):
        log.error("Someone tried deleting something they shouldn't: %s" % dst)
        return
    try:
        storage.delete(dst)
    except Exception, e:
        log.error('Error deleting persona image: %s' % e)


@task
@set_modified_on
def create_persona_preview_image(src, dst, img_basename, **kw):
    """Creates a 680x100 thumbnail used for the Persona preview."""
    log.info('[1@None] Resizing persona image: %s' % dst)
    try:
        preview, full = amo.PERSONA_IMAGE_SIZES['header']
        new_w, new_h = preview
        orig_w, orig_h = full
        with storage.open(src) as fp:
            i = Image.open(fp)
            # Crop image from the right.
            i = i.crop((orig_w - (new_h * 2), 0, orig_w, orig_h))
            i = i.resize(preview, Image.ANTIALIAS)
            i.load()
            with storage.open(os.path.join(dst, img_basename), 'wb') as fp:
                i.save(fp)
        return True
    except Exception, e:
        log.error('Error saving persona image: %s' % e)


@task
@set_modified_on
def save_persona_image(src, dst, img_basename, **kw):
    """Creates a JPG of a Persona header/footer image."""
    log.info('[1@None] Saving persona image: %s' % dst)
    try:
        with storage.open(src) as fp:
            i = Image.open(fp)
            with storage.open(os.path.join(dst, img_basename), 'wb') as fp:
                i.save(fp)
        return True
    except Exception, e:
        log.error('Error saving persona image: %s' % e)


@task
def update_incompatible_appversions(data, **kw):
    """Updates the incompatible_versions table for this version."""
    log.info('Updating incompatible_versions for %s versions.' % len(data))

    for version_id in data:
        # This is here to handle both post_save and post_delete hooks.
        IncompatibleVersions.objects.filter(version=version_id).delete()

        try:
            version = Version.objects.get(pk=version_id)
        except Version.DoesNotExist:
            log.info('Version ID [%d] not found. Incompatible versions were '
                     'cleared.' % version_id)
            return

        try:
            compat = CompatOverride.objects.get(addon=version.addon)
        except CompatOverride.DoesNotExist:
            log.info('Compat override for addon with version ID [%d] not '
                     'found. Incompatible versions were cleared.' % version_id)
            return

        app_ranges = []
        ranges = compat.collapsed_ranges()

        for range in ranges:
            if range.min == '0' and range.max == '*':
                # Wildcard range, add all app ranges
                app_ranges.extend(range.apps)
            elif not range.min_int or not range.max_int:
                if range.min == version.version:
                    app_ranges.extend(range.apps)
            else:
                if (int(range.min_int) <= version.version_int <=
                    int(range.max_int)):
                    app_ranges.extend(range.apps)

        for range in app_ranges:
            IncompatibleVersions.objects.create(version=version,
                                                app_id=range.app.id,
                                                min_app_version=range.min,
                                                max_app_version=range.max)
            log.info('Added incompatible version for version ID [%d]: '
                     'app:%d, %s -> %s' % (version_id, range.app.id, range.min,
                                           range.max))
