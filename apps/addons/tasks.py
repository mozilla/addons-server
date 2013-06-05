import hashlib
import logging
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import connection, transaction

from celeryutils import task
from PIL import Image

from addons.models import Persona
from editors.models import RereviewQueueTheme
import amo
from amo.decorators import set_modified_on, write
from amo.storage_utils import rm_stored_dir
from amo.utils import cache_ns_key, ImageCheck, LocalFileStorage
from lib.es.utils import index_objects
from versions.models import Version

# pulling tasks from cron
from . import cron, search  # NOQA
from .models import (Addon, attach_categories, attach_devices, attach_prices,
                     attach_tags, attach_translations, CompatOverride,
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


@task(acks_late=True)
def index_addons(ids, **kw):
    log.info('Indexing addons %s-%s. [%s]' % (ids[0], ids[-1], len(ids)))
    transforms = (attach_categories, attach_devices, attach_prices,
                  attach_tags, attach_translations)
    index_objects(ids, Addon, search, kw.pop('index', None), transforms)


@task
def unindex_addons(ids, **kw):
    for addon in ids:
        log.info('Removing addon [%s] from search index.' % addon)
        Addon.unindex(addon)


@task
def delete_persona_image(dst, **kw):
    log.info('[1@None] Deleting persona image: %s.' % dst)
    if not dst.startswith(settings.ADDONS_PATH):
        log.error("Someone tried deleting something they shouldn't: %s" % dst)
        return
    try:
        storage.delete(dst)
    except Exception, e:
        log.error('Error deleting persona image: %s' % e)


@set_modified_on
def create_persona_preview_images(src, full_dst, **kw):
    """
    Creates a 680x100 thumbnail used for the Persona preview and
    a 32x32 thumbnail used for search suggestions/detail pages.
    """
    log.info('[1@None] Resizing persona images: %s' % full_dst)
    preview, full = amo.PERSONA_IMAGE_SIZES['header']
    preview_w, preview_h = preview
    orig_w, orig_h = full
    with storage.open(src) as fp:
        i_orig = i = Image.open(fp)

        # Crop image from the right.
        i = i.crop((orig_w - (preview_w * 2), 0, orig_w, orig_h))

        # Resize preview.
        i = i.resize(preview, Image.ANTIALIAS)
        i.load()
        with storage.open(full_dst[0], 'wb') as fp:
            i.save(fp, 'png')

        _, icon_size = amo.PERSONA_IMAGE_SIZES['icon']
        icon_w, icon_h = icon_size

        # Resize icon.
        i = i_orig
        i.load()
        i = i.crop((orig_w - (preview_h * 2), 0, orig_w, orig_h))
        i = i.resize(icon_size, Image.ANTIALIAS)
        i.load()
        with storage.open(full_dst[1], 'wb') as fp:
            i.save(fp, 'png')
    return True


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


def make_checksum(header_path, footer_path):
    ls = LocalFileStorage()
    raw_checksum = ls._open(header_path).read() + ls._open(footer_path).read()
    return hashlib.sha224(raw_checksum).hexdigest()


def theme_checksum(theme, **kw):
    theme.checksum = make_checksum(theme.header_path, theme.footer_path)
    dupe_personas = Persona.objects.filter(checksum=theme.checksum)
    if dupe_personas.exists():
        theme.dupe_persona = dupe_personas[0]
    theme.save()


def rereviewqueuetheme_checksum(rqt, **kw):
    """Check for possible duplicate theme images."""
    dupe_personas = Persona.objects.filter(
        checksum=make_checksum(rqt.header_path or rqt.theme.header_path,
                               rqt.footer_path or rqt.theme.footer_path))
    if dupe_personas.exists():
        rqt.dupe_persona = dupe_personas[0]
        rqt.save()


@task
@write
def save_theme(header, footer, addon, **kw):
    """Save theme image and calculates checksum after theme save."""
    dst_root = os.path.join(settings.ADDONS_PATH, str(addon.id))
    header = os.path.join(settings.TMP_PATH, 'persona_header', header)
    footer = os.path.join(settings.TMP_PATH, 'persona_footer', footer)
    header_dst = os.path.join(dst_root, 'header.png')
    footer_dst = os.path.join(dst_root, 'footer.png')

    try:
        save_persona_image(src=header, full_dst=header_dst)
        save_persona_image(src=footer, full_dst=footer_dst)
        create_persona_preview_images(
            src=header, full_dst=[os.path.join(dst_root, 'preview.png'),
                                  os.path.join(dst_root, 'icon.png')],
            set_modified_on=[addon])
        theme_checksum(addon.persona)
    except IOError:
        addon.delete()
        raise


@task
@write
def save_theme_reupload(header, footer, addon, **kw):
    header_dst = None
    footer_dst = None
    dst_root = os.path.join(settings.ADDONS_PATH, str(addon.id))

    try:
        if header:
            header = os.path.join(settings.TMP_PATH, 'persona_header', header)
            header_dst = os.path.join(dst_root, 'pending_header.png')
            save_persona_image(src=header, full_dst=header_dst)
        if footer:
            footer = os.path.join(settings.TMP_PATH, 'persona_footer', footer)
            footer_dst = os.path.join(dst_root, 'pending_footer.png')
            save_persona_image(src=footer, full_dst=footer_dst)
    except IOError as e:
        log.error(str(e))
        raise

    if header_dst or footer_dst:
        theme = addon.persona
        header = 'pending_header.png' if header_dst else 'header.png'
        footer = 'pending_footer.png' if footer_dst else 'footer.png'

        # Store pending header and/or footer file paths for review.
        RereviewQueueTheme.objects.filter(theme=theme).delete()
        rqt = RereviewQueueTheme.objects.create(
            theme=theme, header=header, footer=footer)
        rereviewqueuetheme_checksum(rqt=rqt)


@task
@write
def calc_checksum(theme_id, **kw):
    """For migration 596."""
    lfs = LocalFileStorage()
    theme = Persona.objects.get(id=theme_id)
    header = theme.header_path
    footer = theme.footer_path

    # Delete invalid themes that are not images (e.g. PDF, EXE).
    try:
        Image.open(header)
        Image.open(footer)
    except IOError:
        log.info('Deleting invalid theme [%s] (header: %s) (footer: %s)' %
                 (theme.addon.id, header, footer))
        theme.addon.delete()
        theme.delete()
        rm_stored_dir(header.replace('header.png', ''), storage=lfs)
        return

    # Calculate checksum and save.
    try:
        theme.checksum = make_checksum(header, footer)
        theme.save()
    except IOError as e:
        log.error(str(e))
