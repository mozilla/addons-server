import hashlib
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import transaction

from elasticsearch_dsl import Search
from PIL import Image

import olympia.core.logger
from olympia import amo
from olympia.addons.models import (
    Addon, attach_tags, attach_translations, AppSupport, CompatOverride,
    IncompatibleVersions, Persona, Preview)
from olympia.addons.indexers import AddonIndexer
from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on, write
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.amo.storage_utils import rm_stored_dir
from olympia.amo.utils import (
    cache_ns_key, ImageCheck, LocalFileStorage, rm_local_tmp_dir)
from olympia.applications.models import AppVersion
from olympia.editors.models import RereviewQueueTheme
from olympia.files.utils import extract_zip, RDFExtractor
from olympia.lib.es.utils import index_objects
from olympia.tags.models import Tag
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.task')


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
    elif addon.status == amo.STATUS_PUBLIC:
        q = 'public'
    else:
        q = 'exp'
    qs = queries[q].filter(pk=addon_id).using('default')
    res = qs.values_list('id', 'last_updated')
    if res:
        pk, t = res[0]
        Addon.objects.filter(pk=pk).update(last_updated=t)


@write
def update_appsupport(ids):
    log.info("[%s@None] Updating appsupport for %s." % (len(ids), ids))

    addons = Addon.objects.no_cache().filter(id__in=ids).no_transforms()
    support = []
    for addon in addons:
        for app, appver in addon.compatible_apps.items():
            if appver is None:
                # Fake support for all version ranges.
                min_, max_ = 0, 999999999999999999
            else:
                min_, max_ = appver.min.version_int, appver.max.version_int

            support.append(AppSupport(addon=addon, app=app.id,
                                      min=min_, max=max_))

    if not support:
        return

    with transaction.atomic():
        AppSupport.objects.filter(addon__id__in=ids).delete()
        AppSupport.objects.bulk_create(support)

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
    transforms = (attach_tags, attach_translations)
    index_objects(ids, Addon, AddonIndexer.extract_document,
                  kw.pop('index', None), transforms, Addon.unfiltered)


@task
def unindex_addons(ids, **kw):
    for addon in ids:
        log.info('Removing addon [%s] from search index.' % addon)
        Addon.unindex(addon)


@task
def delete_persona_image(dst, **kw):
    log.info('[1@None] Deleting persona image: %s.' % dst)
    if not dst.startswith(user_media_path('addons')):
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
                                                app=app_range.app.id,
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
    footer = footer_path and ls._open(footer_path).read() or ''
    raw_checksum = ls._open(header_path).read() + footer
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
    dst_root = os.path.join(user_media_path('addons'), str(addon.id))
    header = os.path.join(settings.TMP_PATH, 'persona_header', header)
    header_dst = os.path.join(dst_root, 'header.png')
    if footer:
        footer = os.path.join(settings.TMP_PATH, 'persona_footer', footer)
        footer_dst = os.path.join(dst_root, 'footer.png')

    try:
        save_persona_image(src=header, full_dst=header_dst)
        if footer:
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
    dst_root = os.path.join(user_media_path('addons'), str(addon.id))

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
        header = 'pending_header.png' if header_dst else theme.header
        # Theme footer is optional, but can't be None.
        footer = theme.footer or ''
        if footer_dst:
            footer = 'pending_footer.png'

        # Store pending header and/or footer file paths for review.
        RereviewQueueTheme.objects.filter(theme=theme).delete()
        rqt = RereviewQueueTheme(theme=theme, header=header, footer=footer)
        rereviewqueuetheme_checksum(rqt=rqt)
        rqt.save()


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


@task
@write  # To bypass cache and use the primary replica.
def find_inconsistencies_between_es_and_db(ids, **kw):
    length = len(ids)
    log.info(
        'Searching for inconsistencies between db and es %d-%d [%d].',
        ids[0], ids[-1], length)
    db_addons = Addon.unfiltered.in_bulk(ids)
    es_addons = Search(
        doc_type=AddonIndexer.get_doctype_name(),
        index=AddonIndexer.get_index_alias(),
        using=amo.search.get_es()).filter('ids', values=ids)[:length].execute()
    es_addons = es_addons
    db_len = len(db_addons)
    es_len = len(es_addons)
    if db_len != es_len:
        log.info('Inconsistency found: %d in db vs %d in es.',
                 db_len, es_len)
    for result in es_addons.hits.hits:
        pk = result['_source']['id']
        db_modified = db_addons[pk].modified.isoformat()
        es_modified = result['_source']['modified']
        if db_modified != es_modified:
            log.info('Inconsistency found for addon %d: '
                     'modified is %s in db vs %s in es.',
                     pk, db_modified, es_modified)
        db_status = db_addons[pk].status
        es_status = result['_source']['status']
        if db_status != es_status:
            log.info('Inconsistency found for addon %d: '
                     'status is %s in db vs %s in es.',
                     pk, db_status, es_status)


@task
@write
def add_firefox57_tag(ids, **kw):
    """Add firefox57 tag to addons with the specified ids."""
    log.info(
        'Adding firefox57 tag to addons %d-%d [%d].',
        ids[0], ids[-1], len(ids))

    addons = Addon.objects.filter(id__in=ids)
    for addon in addons:
        # This will create a couple extra queries to check for tag/addontag
        # existence, and then trigger update_tag_stat tasks. But the
        # alternative is adding activity log manually, making sure we don't
        # add duplicate tags, manually updating the tag stats, so it's ok for
        # a one-off task.
        Tag(tag_text='firefox57').save_tag(addon)


def extract_strict_compatibility_value_for_addon(addon):
    strict_compatibility = None  # We don't know yet.
    extracted_dir = None
    try:
        # We take a shortcut here and only look at the first file we
        # find...
        # Note that we can't use parse_addon() wrapper because it no longer
        # exposes the real value of `strictCompatibility`...
        path = addon.current_version.all_files[0].file_path
        with storage.open(path) as file_:
            extracted_dir = extract_zip(file_)
        parser = RDFExtractor(extracted_dir)
        strict_compatibility = parser.find('strictCompatibility') == 'true'
    except Exception as exp:
        # A number of things can go wrong: missing file, path somehow not
        # existing, etc. In any case, that means the add-on is in a weird
        # state and should be ignored (this is a one off task).
        log.exception(u'bump_appver_for_legacy_addons: ignoring addon %d, '
                      u'received %s when extracting.', addon.pk, unicode(exp))
    finally:
        if extracted_dir:
            rm_local_tmp_dir(extracted_dir)
    return strict_compatibility


def bump_appver_for_addon_if_necessary(
        addon, application_id, new_max_appver, strict_compatibility=None):
    # Find the applicationversion for Firefox for the current version of this
    # addon.
    application_versions = addon.current_version.compatible_apps.get(
        amo.APPS_ALL[application_id])

    # Make sure it's not compatible already...
    if application_versions and (
            application_versions.max.version_int < new_max_appver.version_int):
        if strict_compatibility is None:
            # We don't know yet if the add-on had strictCompatibility enabled
            # (either because it's the first time we called the function for
            # this addon, or because it was not neccessary to bump the last
            # time we called, or because we had an error before). Let's parse
            # it to find out.
            strict_compatibility = (
                extract_strict_compatibility_value_for_addon(addon))
        if strict_compatibility is False:
            # It had not enabled strict compatibility. That means we should
            # bump it!
            application_versions.max = new_max_appver
            application_versions.save()
    return strict_compatibility


# Rate limit is per-worker. Kept low to not overload the database with updates.
# We have 5 workers in the default queue, we have roughly 25.000 add-ons to go
# through, since process_addons() chunks contain 100 add-ons the task should be
# fired 250 times. With 5 workers at 5 tasks / minute limit we should do 25
# tasks in a minute, taking ~ 10 minutes for the whole thing to finish.
@task(rate_limit='5/m')
@write
def bump_appver_for_legacy_addons(ids, **kw):
    """
    Task to bump the max appversion to 56.* for legacy add-ons that have not
    enabled strictCompatibility in their manifest.
    """
    addons = Addon.objects.filter(id__in=ids)
    # The AppVersions we want to point to now.
    new_max_appversions = {
        amo.FIREFOX.id: AppVersion.objects.get(
            application=amo.FIREFOX.id, version='56.*'),
        amo.ANDROID.id: AppVersion.objects.get(
            application=amo.ANDROID.id, version='56.*')
    }

    addons_to_reindex = []
    for addon in addons:
        strict_compatibility = bump_appver_for_addon_if_necessary(
            addon, amo.FIREFOX.id, new_max_appversions[amo.FIREFOX.id])
        # If strict_compatibility is True, we know we should skip bumping this
        # add-on entirely. Otherwise (False or None), we need to continue with
        # Firefox for Android, which might have different compat info than
        # Firefox. We pass the value we already have for strict_compatibility,
        # if it's not None bump_appver_for_addon_if_necessary() will avoid
        # re-extracting a second time.
        if strict_compatibility is not True:
            android_strict_compatibility = bump_appver_for_addon_if_necessary(
                addon, amo.ANDROID.id, new_max_appversions[amo.ANDROID.id],
                strict_compatibility=strict_compatibility)

            if (android_strict_compatibility is False or
                    strict_compatibility is False):
                # We did something to that add-on compat, it needs reindexing.
                addons_to_reindex.append(addon.pk)
    if addons_to_reindex:
        index_addons.delay(addons_to_reindex)
