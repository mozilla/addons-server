import hashlib

from json import JSONDecodeError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage as storage
from django.db import transaction

import waffle

from elasticsearch_dsl import Search
from PIL import Image

import olympia.core

from olympia import amo
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AppSupport,
    CompatOverride, IncompatibleVersions, MigratedLWT, Preview,
    attach_tags, attach_translations)
from olympia.amo.celery import pause_all_tasks, resume_all_tasks, task
from olympia.amo.decorators import set_modified_on, use_primary_db
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.amo.utils import (
    ImageCheck, LocalFileStorage, StopWatch,
    extract_colors_from_image, pngcrush_image)
from olympia.files.utils import get_filepath, parse_addon
from olympia.lib.crypto.signing import SigningError
from olympia.lib.es.utils import index_objects
from olympia.tags.models import Tag
from olympia.users.models import UserProfile
from olympia.versions.models import (
    generate_static_theme_preview, Version, VersionPreview)
from olympia.versions.utils import (
    new_69_theme_properties_from_old, new_theme_version_with_69_properties)


log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
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
    elif addon.status == amo.STATUS_APPROVED:
        q = 'public'
    else:
        q = 'exp'
    qs = queries[q].filter(pk=addon_id).using('default')
    res = qs.values_list('id', 'last_updated')
    if res:
        pk, t = res[0]
        Addon.objects.filter(pk=pk).update(last_updated=t)


@task
@use_primary_db
def update_appsupport(ids, **kw):
    log.info("[%s@None] Updating appsupport for %s." % (len(ids), ids))

    addons = Addon.objects.filter(id__in=ids).no_transforms()
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


@task
def update_addon_average_daily_users(data, **kw):
    log.info("[%s] Updating add-ons ADU totals." % (len(data)))

    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    for pk, count in data:
        try:
            addon = Addon.objects.get(pk=pk)
        except Addon.DoesNotExist:
            # The processing input comes from metrics which might be out of
            # date in regards to currently existing add-ons
            m = "Got an ADU update (%s) but the add-on doesn't exist (%s)"
            log.debug(m % (count, pk))
            continue

        addon.update(average_daily_users=int(float(count)))


@task
def update_addon_download_totals(data, **kw):
    log.info('[%s] Updating add-ons download+average totals.' % (len(data)))

    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    for pk, sum_download_counts in data:
        try:
            addon = Addon.objects.get(pk=pk)
            # Don't trigger a save unless we have to (the counts may not have
            # changed)
            if (sum_download_counts and
                    addon.total_downloads != sum_download_counts):
                addon.update(total_downloads=sum_download_counts)
        except Addon.DoesNotExist:
            # We exclude deleted add-ons in the cron, but an add-on could have
            # been deleted by the time the task is processed.
            msg = ("Got new download totals (total=%s) but the add-on"
                   "doesn't exist (%s)" % (sum_download_counts, pk))
            log.debug(msg)


@task
def delete_preview_files(id, **kw):
    Preview.delete_preview_files(sender=None, instance=Preview(id=id))


@task(acks_late=True)
@use_primary_db
def index_addons(ids, **kw):
    log.info('Indexing addons %s-%s. [%s]' % (ids[0], ids[-1], len(ids)))
    transforms = (attach_tags, attach_translations)
    index_objects(ids, Addon, AddonIndexer.extract_document,
                  kw.pop('index', None), transforms, Addon.unfiltered)


@task
@use_primary_db
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
    except Exception as e:
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
    pngcrush_image(full_dst[0])
    pngcrush_image(full_dst[1])
    return True


@set_modified_on
def save_persona_image(src, full_dst, **kw):
    """Creates a PNG of a Persona header image."""
    log.info('[1@None] Saving persona image: %s' % full_dst)
    img = ImageCheck(storage.open(src))
    if not img.is_image():
        log.error('Not an image: %s' % src, exc_info=True)
        return
    with storage.open(src, 'rb') as fp:
        i = Image.open(fp)
        with storage.open(full_dst, 'wb') as fp:
            i.save(fp, 'png')
    pngcrush_image(full_dst)
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


def make_checksum(header_path):
    ls = LocalFileStorage()
    raw_checksum = ls._open(header_path).read()
    return hashlib.sha224(raw_checksum).hexdigest()


@task
@use_primary_db  # To bypass cache and use the primary replica.
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
@use_primary_db
def add_dynamic_theme_tag(ids, **kw):
    """Add dynamic theme tag to addons with the specified ids."""
    log.info(
        'Adding  dynamic theme tag to addons %d-%d [%d].',
        ids[0], ids[-1], len(ids))

    addons = Addon.objects.filter(id__in=ids)
    for addon in addons:
        files = addon.current_version.all_files
        if any('theme' in file_.webext_permissions_list for file_ in files):
            Tag(tag_text='dynamic theme').save_tag(addon)
            index_addons.delay([addon.id])


# Rate limiting to 1 per minute to not overload our networking filesystem
# and block our celery workers. Extraction to our git backend doesn't have
# to be fast. Each instance processes 100 add-ons so we'll process
# 6000 add-ons per hour which is fine.
@task(rate_limit='1/m')
def migrate_webextensions_to_git_storage(ids, **kw):
    # recursive imports...
    from olympia.versions.tasks import (
        extract_version_to_git, extract_version_source_to_git)

    log.info(
        'Migrating add-ons to git storage %d-%d [%d].',
        ids[0], ids[-1], len(ids))

    addons = Addon.unfiltered.filter(id__in=ids)

    for addon in addons:
        # Filter out versions that are already present in the git
        # storage.
        versions = addon.versions.filter(git_hash='').order_by('created')

        for version in versions:
            # Back in the days an add-on was able to have multiple files
            # per version. That changed, we are very naive here and extracting
            # simply the first file in the list. For WebExtensions there is
            # only a very very small number that have different files for
            # a single version.
            unique_file_hashes = set([
                x.original_hash for x in version.all_files
            ])

            if len(unique_file_hashes) > 1:
                # Log actually different hashes so that we can clean them
                # up manually and work together with developers later.
                log.info(
                    'Version {version} of {addon} has more than one uploaded '
                    'file'.format(version=repr(version), addon=repr(addon)))

            if not unique_file_hashes:
                log.info('No files found for {version} from {addon}'.format(
                    version=repr(version), addon=repr(addon)))
                continue

            # Don't call the task as a task but do the extraction in process
            # this makes sure we don't overwhelm the storage and also makes
            # sure we don't end up with tasks committing at random times but
            # correctly in-order instead.
            try:
                file_id = version.all_files[0].pk

                log.info('Extracting file {file_id} to git storage'.format(
                    file_id=file_id))

                extract_version_to_git(version.pk)

                if version.source:
                    extract_version_source_to_git(version.pk)

                log.info(
                    'Extraction of file {file_id} into git storage succeeded'
                    .format(file_id=file_id))
            except Exception:
                log.exception(
                    'Extraction of file {file_id} from {version} '
                    '({addon}) failed'.format(
                        file_id=version.all_files[0],
                        version=repr(version),
                        addon=repr(addon)))
                continue


@task
@use_primary_db
def extract_colors_from_static_themes(ids, **kw):
    """Extract and store colors from existing static themes."""
    log.info('Extracting static themes colors %d-%d [%d].', ids[0], ids[-1],
             len(ids))
    addons = Addon.objects.filter(id__in=ids)
    extracted = []
    for addon in addons:
        first_preview = addon.current_previews.first()
        if first_preview and not first_preview.colors:
            colors = extract_colors_from_image(first_preview.thumbnail_path)
            addon.current_previews.update(colors=colors)
            extracted.append(addon.pk)
    if extracted:
        index_addons.delay(extracted)


@task
@use_primary_db
def recreate_theme_previews(addon_ids, **kw):
    log.info('[%s@%s] Recreating previews for themes starting at id: %s...'
             % (len(addon_ids), recreate_theme_previews.rate_limit,
                addon_ids[0]))
    addons = Addon.objects.filter(pk__in=addon_ids).no_transforms()
    only_missing = kw.get('only_missing', False)

    for addon in addons:
        version = addon.current_version
        if not version:
            continue
        try:
            if only_missing:
                with_size = (VersionPreview.objects.filter(version=version)
                             .exclude(sizes={}).count())
                if with_size == len(amo.THEME_PREVIEW_SIZES):
                    continue
            log.info('Recreating previews for theme: %s' % addon.id)
            VersionPreview.objects.filter(version=version).delete()
            xpi = get_filepath(version.all_files[0])
            theme_data = parse_addon(xpi, minimal=True).get('theme', {})
            generate_static_theme_preview(theme_data, version.id)
        except IOError:
            pass


@task
@use_primary_db
def delete_addons(addon_ids, **kw):
    log.info('[%s@%s] Deleting addons starting at id: %s...'
             % (len(addon_ids), delete_addons.rate_limit, addon_ids[0]))
    addons = Addon.objects.filter(pk__in=addon_ids).no_transforms()
    for addon in addons:
        addon.delete(send_delete_email=False)


@task
@use_primary_db
def repack_themes_for_69(addon_ids, **kw):
    log.info(
        '[%s@%s] Repacking themes to use 69+ properties starting at id: %s...'
        % (len(addon_ids), recreate_theme_previews.rate_limit, addon_ids[0]))
    addons = Addon.objects.filter(pk__in=addon_ids).no_transforms()

    olympia.core.set_user(UserProfile.objects.get(pk=settings.TASK_USER_ID))
    for addon in addons:
        version = addon.current_version
        log.info('[CHECK] theme [%r] for deprecated properties' % addon)
        if not version:
            log.info('[INVALID] theme [%r] has no current_version' % addon)
            continue
        pause_all_tasks()
        try:
            timer = StopWatch('addons.tasks.repack_themes_for_69')
            timer.start()
            old_xpi = get_filepath(version.all_files[0])
            old_data = parse_addon(old_xpi, minimal=True)
            new_data = new_69_theme_properties_from_old(old_data)
            if new_data != old_data:
                # if the manifest isn't the same let's repack
                new_version = new_theme_version_with_69_properties(version)
                log.info('[SUCCESS] Theme [%r], version [%r] updated to [%r]' %
                         (addon, version, new_version))
            else:
                log.info('[SKIP] No need for theme repack [%s]' % addon.id)
            timer.log_interval('')
        except (IOError, ValidationError, JSONDecodeError, SigningError) as ex:
            log.debug('[FAIL] Theme repack for [%r]:', addon, exc_info=ex)
        finally:
            resume_all_tasks()


@task
@use_primary_db
def content_approve_migrated_themes(ids, **kw):
    log.info('[%s@None] Marking migrated static themes as content-reviewed %s.'
             % (len(ids), ids))
    addons = Addon.objects.filter(pk__in=ids)
    for addon in addons:
        try:
            migrated_date = MigratedLWT.objects.get(static_theme=addon).created
        except MigratedLWT.DoesNotExist:
            continue
        AddonApprovalsCounter.approve_content_for_addon(
            addon=addon, now=migrated_date)
