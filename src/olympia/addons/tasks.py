import hashlib
import os
import uuid

from datetime import datetime

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import transaction
from django.utils import translation

import waffle

from django_statsd.clients import statsd
from elasticsearch_dsl import Search
from PIL import Image

import olympia.core

from olympia import activity, amo
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import (
    Addon, AddonCategory, AppSupport, Category, CompatOverride,
    IncompatibleVersions, MigratedLWT, Persona, Preview, attach_tags,
    attach_translations)
from olympia.addons.utils import build_static_theme_xpi_from_lwt
from olympia.bandwagon.models import CollectionAddon
from olympia.amo.celery import pause_all_tasks, resume_all_tasks, task
from olympia.amo.decorators import set_modified_on, use_primary_db
from olympia.amo.storage_utils import rm_stored_dir
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.amo.utils import (
    ImageCheck, LocalFileStorage, StopWatch, cache_ns_key,
    extract_colors_from_image, pngcrush_image)
from olympia.constants.categories import CATEGORIES
from olympia.constants.licenses import (
    LICENSE_COPYRIGHT_AR, PERSONA_LICENSES_IDS)
from olympia.files.models import FileUpload
from olympia.files.utils import get_filepath, parse_addon
from olympia.lib.crypto.signing import sign_file
from olympia.lib.es.utils import index_objects
from olympia.ratings.models import Rating
from olympia.stats.utils import migrate_theme_update_count
from olympia.tags.models import AddonTag, Tag
from olympia.users.models import UserProfile
from olympia.versions.models import (
    generate_static_theme_preview, License, Version, VersionPreview)


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
    elif addon.status == amo.STATUS_PUBLIC:
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

    # Increment namespace cache of compat versions.
    for addon_id in addon_ids:
        cache_ns_key('d2c-versions:%s' % addon_id, increment=True)


def make_checksum(header_path):
    ls = LocalFileStorage()
    raw_checksum = ls._open(header_path).read()
    return hashlib.sha224(raw_checksum).hexdigest()


def theme_checksum(theme, **kw):
    theme.checksum = make_checksum(theme.header_path)
    dupe_personas = Persona.objects.filter(checksum=theme.checksum)
    if dupe_personas.exists():
        theme.dupe_persona = dupe_personas[0]
    theme.save()


def rereviewqueuetheme_checksum(rqt, **kw):
    """Check for possible duplicate theme images."""
    dupe_personas = Persona.objects.filter(
        checksum=make_checksum(rqt.header_path or rqt.theme.header_path)
    )
    if dupe_personas.exists():
        rqt.dupe_persona = dupe_personas[0]
        rqt.save()


@task
@use_primary_db
def save_theme(header, addon_pk, **kw):
    """Save theme image and calculates checksum after theme save."""
    addon = Addon.objects.get(pk=addon_pk)
    dst_root = os.path.join(user_media_path('addons'), str(addon.id))
    header = os.path.join(settings.TMP_PATH, 'persona_header', header)
    header_dst = os.path.join(dst_root, 'header.png')

    try:
        save_persona_image(src=header, full_dst=header_dst)
        create_persona_preview_images(
            src=header, full_dst=[os.path.join(dst_root, 'preview.png'),
                                  os.path.join(dst_root, 'icon.png')],
            set_modified_on=addon.serializable_reference())
        theme_checksum(addon.persona)
    except IOError:
        addon.delete()
        raise


@task
@use_primary_db
def save_theme_reupload(header, addon_pk, **kw):
    addon = Addon.objects.get(pk=addon_pk)
    header_dst = None
    dst_root = os.path.join(user_media_path('addons'), str(addon.id))

    try:
        if header:
            header = os.path.join(settings.TMP_PATH, 'persona_header', header)
            header_dst = os.path.join(dst_root, 'pending_header.png')
            save_persona_image(src=header, full_dst=header_dst)
    except IOError as e:
        log.error(str(e))
        raise

    if header_dst:
        theme = addon.persona
        header = 'pending_header.png' if header_dst else theme.header


@task
@use_primary_db
def calc_checksum(theme_id, **kw):
    """For migration 596."""
    lfs = LocalFileStorage()
    theme = Persona.objects.get(id=theme_id)
    header = theme.header_path

    # Delete invalid themes that are not images (e.g. PDF, EXE).
    try:
        Image.open(header)
    except IOError:
        log.info('Deleting invalid theme [%s] (header: %s)' %
                 (theme.addon.id, header))
        theme.addon.delete()
        theme.delete()
        rm_stored_dir(header.replace('header.png', ''), storage=lfs)
        return

    # Calculate checksum and save.
    try:
        theme.checksum = make_checksum(header)
        theme.save()
    except IOError as e:
        log.error(str(e))


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


def _get_lwt_default_author():
    user, created = UserProfile.objects.get_or_create(
        email=settings.MIGRATED_LWT_DEFAULT_OWNER_EMAIL)
    if created:
        user.anonymize_username()
    return user


@transaction.atomic
@statsd.timer('addons.tasks.migrate_lwts_to_static_theme.add_from_lwt')
def add_static_theme_from_lwt(lwt):
    from olympia.activity.models import AddonLog

    timer = StopWatch(
        'addons.tasks.migrate_lwts_to_static_theme.add_from_lwt.')
    timer.start()

    olympia.core.set_user(UserProfile.objects.get(pk=settings.TASK_USER_ID))
    # Try to handle LWT with no authors
    author = (lwt.listed_authors or [_get_lwt_default_author()])[0]
    # Wrap zip in FileUpload for Addon/Version from_upload to consume.
    upload = FileUpload.objects.create(
        user=author, valid=True)
    filename = uuid.uuid4().hex + '.xpi'
    destination = os.path.join(user_media_path('addons'), 'temp', filename)
    build_static_theme_xpi_from_lwt(lwt, destination)
    upload.update(path=destination, name=filename)
    timer.log_interval('1.build_xpi')

    # Create addon + version
    parsed_data = parse_addon(upload, user=author)
    timer.log_interval('2a.parse_addon')

    addon = Addon.initialize_addon_from_upload(
        parsed_data, upload, amo.RELEASE_CHANNEL_LISTED, author)
    addon_updates = {}
    timer.log_interval('2b.initialize_addon')

    # static themes are only compatible with Firefox at the moment,
    # not Android
    version = Version.from_upload(
        upload, addon, selected_apps=[amo.FIREFOX.id],
        channel=amo.RELEASE_CHANNEL_LISTED,
        parsed_data=parsed_data)
    timer.log_interval('3.initialize_version')

    # Set category
    lwt_category = (lwt.categories.all() or [None])[0]  # lwt only have 1 cat.
    lwt_category_slug = lwt_category.slug if lwt_category else 'other'
    for app, type_dict in CATEGORIES.items():
        static_theme_categories = type_dict.get(amo.ADDON_STATICTHEME, [])
        static_category = static_theme_categories.get(
            lwt_category_slug, static_theme_categories.get('other'))
        AddonCategory.objects.create(
            addon=addon,
            category=Category.from_static_category(static_category, True))
    timer.log_interval('4.set_categories')

    # Set license
    lwt_license = PERSONA_LICENSES_IDS.get(
        lwt.persona.license, LICENSE_COPYRIGHT_AR)  # default to full copyright
    static_license = License.objects.get(builtin=lwt_license.builtin)
    version.update(license=static_license)
    timer.log_interval('5.set_license')

    # Set tags
    for addon_tag in AddonTag.objects.filter(addon=lwt):
        AddonTag.objects.create(addon=addon, tag=addon_tag.tag)
    timer.log_interval('6.set_tags')

    # Steal the ratings (even with soft delete they'll be deleted anyway)
    addon_updates.update(
        average_rating=lwt.average_rating,
        bayesian_rating=lwt.bayesian_rating,
        total_ratings=lwt.total_ratings,
        text_ratings_count=lwt.text_ratings_count)
    Rating.unfiltered.filter(addon=lwt).update(addon=addon, version=version)
    timer.log_interval('7.move_ratings')

    # Replace the lwt in collections
    CollectionAddon.objects.filter(addon=lwt).update(addon=addon)

    # Modify the activity log entry too.
    rating_activity_log_ids = [
        l.id for l in amo.LOG if getattr(l, 'action_class', '') == 'review']
    addonlog_qs = AddonLog.objects.filter(
        addon=lwt, activity_log__action__in=rating_activity_log_ids)
    [alog.transfer(addon) for alog in addonlog_qs.iterator()]
    timer.log_interval('8.move_activity_logs')

    # Copy the ADU statistics - the raw(ish) daily UpdateCounts for stats
    # dashboard and future update counts, and copy the average_daily_users.
    # hotness will be recalculated by the deliver_hotness() cron in a more
    # reliable way that we could do, so skip it entirely.
    migrate_theme_update_count(lwt, addon)
    addon_updates.update(
        average_daily_users=lwt.persona.popularity or 0,
        hotness=0)
    timer.log_interval('9.copy_statistics')

    # Logging
    activity.log_create(
        amo.LOG.CREATE_STATICTHEME_FROM_PERSONA, addon, user=author)

    # And finally sign the files (actually just one)
    for file_ in version.all_files:
        sign_file(file_)
        file_.update(
            datestatuschanged=lwt.last_updated,
            reviewed=datetime.now(),
            status=amo.STATUS_PUBLIC)
    timer.log_interval('10.sign_files')
    addon_updates['status'] = amo.STATUS_PUBLIC

    # set the modified and creation dates to match the original.
    addon_updates['created'] = lwt.created
    addon_updates['modified'] = lwt.modified
    addon_updates['last_updated'] = lwt.last_updated

    addon.update(**addon_updates)
    return addon


@task
@use_primary_db
def migrate_lwts_to_static_themes(ids, **kw):
    """With the specified ids, create new static themes based on an existing
    lightweight themes (personas), and delete the lightweight themes after."""
    mlog = olympia.core.logger.getLogger('z.task.lwtmigrate')
    mlog.info(
        '[Info] Migrating LWT to static theme %d-%d [%d].', ids[0], ids[-1],
        len(ids))

    # Incoming ids should already by type=persona only
    lwts = Addon.objects.filter(id__in=ids)
    for lwt in lwts:
        static = None
        pause_all_tasks()
        try:
            timer = StopWatch('addons.tasks.migrate_lwts_to_static_theme')
            timer.start()
            with translation.override(lwt.default_locale):
                static = add_static_theme_from_lwt(lwt)
            mlog.info(
                '[Success] Static theme %r created from LWT %r', static, lwt)
            if not static:
                raise Exception('add_static_theme_from_lwt returned falsey')
            MigratedLWT.objects.create(
                lightweight_theme=lwt, getpersonas_id=lwt.persona.persona_id,
                static_theme=static)
            # Steal the lwt's slug after it's deleted.
            slug = lwt.slug
            lwt.delete(send_delete_email=False)
            static.update(slug=slug)
            timer.log_interval('')
        except Exception as e:
            # If something went wrong, don't migrate - we need to debug.
            mlog.debug('[Fail] LWT %r:', lwt, exc_info=e)
        finally:
            resume_all_tasks()


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
