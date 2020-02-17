import hashlib

from django.db import transaction

import waffle

from elasticsearch_dsl import Search

import olympia.core

from olympia import amo
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AppSupport, MigratedLWT, Preview,
    attach_tags, attach_translations)
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import LocalFileStorage, extract_colors_from_image
from olympia.files.utils import get_filepath, parse_addon
from olympia.lib.es.utils import index_objects
from olympia.tags.models import Tag
from olympia.versions.models import (
    generate_static_theme_preview, VersionPreview)


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

    if addon.status == amo.STATUS_APPROVED:
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
def delete_addons(addon_ids, with_deleted=False, **kw):
    """Delete the given addon ids.

    If `with_deleted=True` the delete is a hard delete - i.e. the addon record
    and all linked records in other models are deleted from the database. We
    use the queryset delete method to bypass Addon.delete().

    If `with_deleted=False` Addon.delete() is called for each addon id, which
    typically* soft deletes - i.e. some metadata and files are removed but the
    records in the database persist, and the Addon.status is set to
    STATUS_DELETED.  *Addon.delete() only does a hard-delete where the Addon
    has no versions or files - and has never had any versions or files.
    """
    log.info('[%s@%s] %sDeleting addons starting at id: %s...'
             % ('Hard ' if with_deleted else '', len(addon_ids),
                delete_addons.rate_limit, addon_ids[0]))
    addons = Addon.unfiltered.filter(pk__in=addon_ids).no_transforms()
    if with_deleted:
        # Call QuerySet.delete rather than Addon.delete.
        addons.delete()
    else:
        for addon in addons:
            addon.delete(send_delete_email=False)


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
