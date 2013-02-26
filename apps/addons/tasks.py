import os
import logging

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import connection, transaction

from celeryutils import task
from PIL import Image

import amo
from amo.decorators import set_modified_on, write
from amo.utils import (attach_trans_dict, cache_ns_key, sorted_groupby,
                       ImageCheck)
from lib.es.hold import add
from lib.es.utils import index_objects
from market.models import AddonPremium
from tags.models import Tag
from versions.models import Version

# pulling tasks from cron
from . import cron, search  # NOQA
from .models import (Addon, AddonDeviceType, Category, CompatOverride,
                     IncompatibleVersions, Preview)


log = logging.getLogger('z.task')


@task
@write
def version_changed(addon_id, **kw):
    update_last_updated(addon_id)
    update_appsupport([addon_id])


def update_last_updated(addon_id):
    queries = Addon._last_updated_queries()
    try:
        addon = Addon.objects.get(pk=addon_id)
    except Addon.DoesNotExist:
        log.info('[1@None] Updating last updated for %s failed, no addon found'
                 % addon_id)
        return

    log.info('[1@None] Updating last updated for %s.' % addon_id)

    if addon.is_persona():
        q = 'personas'
    elif addon.is_webapp():
        q = 'webapps'
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


def index_addon_held(ids, **kw):
    # Hold the indexes till the end of the request or until lib.es signal,
    # process is called.
    for pk in ids:
        add(index_addons, pk)


@task
def index_addons(ids, **kw):
    log.info('Indexing addons %s-%s. [%s]' % (ids[0], ids[-1], len(ids)))
    transforms = (attach_categories, attach_devices, attach_prices,
                  attach_tags, attach_translations)
    index_objects(ids, Addon, search, kw.pop('index', None), transforms)


def attach_devices(addons):
    addon_dict = dict((a.id, a) for a in addons if a.type == amo.ADDON_WEBAPP)
    devices = (AddonDeviceType.objects.filter(addon__in=addon_dict)
               .values_list('addon', 'device_type'))
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
def create_persona_preview_image(src, full_dst, **kw):
    """Creates a 680x100 thumbnail used for the Persona preview."""
    log.info('[1@None] Resizing persona image: %s' % full_dst)
    preview, full = amo.PERSONA_IMAGE_SIZES['header']
    new_w, new_h = preview
    orig_w, orig_h = full
    with storage.open(src) as fp:
        i = Image.open(fp)
        # Crop image from the right.
        i = i.crop((orig_w - (new_w * 2), 0, orig_w, orig_h))
        i = i.resize(preview, Image.ANTIALIAS)
        i.load()
        with storage.open(full_dst, 'wb') as fp:
            i.save(fp, 'png')
    return True


@task
@set_modified_on
def save_persona_image(src, full_dst, **kw):
    """Creates a PNG of a Persona header/footer image."""
    log.info('[1@None] Saving persona image: %s' % full_dst)
    img = ImageCheck(storage.open(src))
    if not img.is_image():
        log.error('Not an image: %s' % src, exc_info=True)
        return
    with storage.open(src, 'rb') as fp:
        i = Image.open(fp)
        with storage.open(full_dst, 'wb') as fp:
            i.save(fp, 'png')
    return True


@task
def update_incompatible_appversions(data, **kw):
    """Updates the incompatible_versions table for this version."""
    log.info('Updating incompatible_versions for %s versions.' % len(data))

    addon_ids = set()

    for version_id in data:
        # This is here to handle both post_save and post_delete hooks.
        IncompatibleVersions.objects.filter(version=version_id).delete()

        try:
            version = Version.objects.get(pk=version_id)
        except Version.DoesNotExist:
            log.info('Version ID [%d] not found. Incompatible versions were '
                     'cleared.' % version_id)
            return

        addon_ids.add(version.addon_id)

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
            else:
                # Since we can't rely on add-on version numbers, get the min
                # and max ID values and find versions whose ID is within those
                # ranges, being careful with wildcards.
                min_id = max_id = None

                if range.min == '0':
                    versions = (Version.objects.filter(addon=version.addon_id)
                                .order_by('id')
                                .values_list('id', flat=True)[:1])
                    if versions:
                        min_id = versions[0]
                else:
                    try:
                        min_id = Version.objects.get(addon=version.addon_id,
                                                     version=range.min).id
                    except Version.DoesNotExist:
                        pass

                if range.max == '*':
                    versions = (Version.objects.filter(addon=version.addon_id)
                                .order_by('-id')
                                .values_list('id', flat=True)[:1])
                    if versions:
                        max_id = versions[0]
                else:
                    try:
                        max_id = Version.objects.get(addon=version.addon_id,
                                                     version=range.max).id
                    except Version.DoesNotExist:
                        pass

                if min_id and max_id:
                    if min_id <= version.id <= max_id:
                        app_ranges.extend(range.apps)

        for app_range in app_ranges:
            IncompatibleVersions.objects.create(version=version,
                                                app_id=app_range.app.id,
                                                min_app_version=app_range.min,
                                                max_app_version=app_range.max)
            log.info('Added incompatible version for version ID [%d]: '
                     'app:%d, %s -> %s' % (version_id, app_range.app.id,
                                           app_range.min, app_range.max))

    # Increment namespace cache of compat versions.
    for addon_id in addon_ids:
        cache_ns_key('d2c-versions:%s' % addon_id, increment=True)
