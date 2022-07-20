import hashlib
import os

from django.db import transaction
from django.db.models import Value
from django.db.models.functions import Collate

from elasticsearch import TransportError
from elasticsearch_dsl import Search

import olympia.core

from olympia import activity, amo
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import (
    Addon,
    DeniedGuid,
    Preview,
    attach_tags,
    attach_translations_dict,
)
from olympia.addons.utils import compute_last_updated
from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on, use_primary_db
from olympia.amo.utils import extract_colors_from_image
from olympia.devhub.tasks import resize_image
from olympia.files.models import File
from olympia.files.utils import get_filepath, parse_addon
from olympia.search.utils import get_es, index_objects
from olympia.users.utils import get_task_user
from olympia.versions.models import Version, VersionPreview
from olympia.versions.tasks import generate_static_theme_preview


log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
def version_changed(addon_id, **kw):
    try:
        addon = Addon.objects.get(pk=addon_id)
    except Addon.DoesNotExist:
        log.info(
            '[1@None] Updating last updated for %s failed, no addon found' % addon_id
        )
        return
    log.info('[1@None] Updating last updated for %s.' % addon.pk)
    addon.update(last_updated=compute_last_updated(addon))


@task
def update_addon_average_daily_users(data, **kw):
    log.info('[%s] Updating add-ons ADU totals.' % (len(data)))

    for addon_guid, count in data:
        try:
            # guids are technically case-insensitive in AMO, but not in
            # BigQuery, so we may be receiving the same guid multiple times in
            # different cases. We want to avoid accidentally overwriting the
            # value in the database, so we force an exact match here.
            addon = Addon.unfiltered.get(guid=Collate(Value(addon_guid), 'utf8mb4_bin'))
        except Addon.DoesNotExist:
            # The processing input comes from metrics which might be out of
            # date in regards to currently existing add-ons
            m = "Got an ADU update (%s) but the add-on doesn't exist (%s)"
            log.info(m % (count, addon_guid))
            continue

        addon.update(average_daily_users=int(float(count)))


@task
def delete_preview_files(id, **kw):
    Preview.delete_preview_files(sender=None, instance=Preview(id=id))


@task(acks_late=True)
@use_primary_db
def index_addons(ids, **kw):
    log.info(f'Indexing addons {ids[0]}-{ids[-1]}. [{len(ids)}]')
    transforms = (attach_tags, attach_translations_dict)
    index_objects(
        ids=ids,
        indexer_class=AddonIndexer,
        index=kw.pop('index', None),
        transforms=transforms,
        manager_name='unfiltered',
    )


@task
@use_primary_db
def unindex_addons(ids, **kw):
    es = get_es()
    for addon_id in ids:
        log.info('Removing addon [%s] from search index.' % addon_id)
        try:
            es.delete(
                AddonIndexer.get_index_alias(),
                AddonIndexer.get_doctype_name(),
                addon_id,
            )
        except TransportError:
            # We ignore already deleted add-ons.
            pass


@task
@use_primary_db  # To bypass cache and use the primary replica.
def find_inconsistencies_between_es_and_db(ids, **kw):
    length = len(ids)
    log.info(
        'Searching for inconsistencies between db and es %d-%d [%d].',
        ids[0],
        ids[-1],
        length,
    )
    db_addons = Addon.unfiltered.in_bulk(ids)
    es_addons = (
        Search(
            index=AddonIndexer.get_index_alias(),
            using=get_es(),
        )
        .filter('ids', values=ids)[:length]
        .execute()
    )
    es_addons = es_addons
    db_len = len(db_addons)
    es_len = len(es_addons)
    if db_len != es_len:
        log.info('Inconsistency found: %d in db vs %d in es.', db_len, es_len)
    for result in es_addons.hits.hits:
        pk = result['_source']['id']
        db_modified = db_addons[pk].modified.isoformat()
        es_modified = result['_source']['modified']
        if db_modified != es_modified:
            log.info(
                'Inconsistency found for addon %d: '
                'modified is %s in db vs %s in es.',
                pk,
                db_modified,
                es_modified,
            )
        db_status = db_addons[pk].status
        es_status = result['_source']['status']
        if db_status != es_status:
            log.info(
                'Inconsistency found for addon %d: status is %s in db vs %s in es.',
                pk,
                db_status,
                es_status,
            )


@task
@use_primary_db
def extract_colors_from_static_themes(ids, **kw):
    """Extract and store colors from existing static themes."""
    log.info('Extracting static themes colors %d-%d [%d].', ids[0], ids[-1], len(ids))
    addons = Addon.objects.filter(id__in=ids)
    extracted = []
    for addon in addons:
        if addon.current_previews and not addon.current_previews[0].colors:
            colors = extract_colors_from_image(addon.current_previews[0].thumbnail_path)
            addon.current_version.previews.update(colors=colors)
            del addon.current_previews
            extracted.append(addon.pk)
    if extracted:
        index_addons.delay(extracted)


@task
@use_primary_db
def recreate_theme_previews(addon_ids, **kw):
    log.info(
        '[%s@%s] Recreating previews for themes starting at id: %s...'
        % (len(addon_ids), recreate_theme_previews.rate_limit, addon_ids[0])
    )
    version_ids = Addon.objects.filter(pk__in=addon_ids).values_list('_current_version')
    versions = Version.objects.filter(pk__in=version_ids)
    only_missing = kw.get('only_missing', False)

    renders = {
        (render['full'], render['image_format']): {
            'thumb_size': render['thumbnail'],
            'thumb_format': render['thumbnail_format'],
        }
        for render in amo.THEME_PREVIEW_RENDERINGS.values()
    }

    for version in versions:
        try:
            if only_missing:
                existing_full_sizes = {
                    (tuple(size.get('image', ())), size.get('image_format', 'png'))
                    for size in VersionPreview.objects.filter(
                        version=version
                    ).values_list('sizes', flat=True)
                }
                all_full_sizes_present = not set(renders.keys()) - existing_full_sizes
                if all_full_sizes_present:
                    # i.e. we have all renders
                    log.info('Resizing thumbnails for theme: %s' % version.addon_id)
                    for preview in list(VersionPreview.objects.filter(version=version)):
                        # so check the thumbnail size/format for each preview
                        preview_dimension_format = (
                            tuple(preview.image_dimensions),
                            preview.get_format('image'),
                        )
                        render = renders.get(preview_dimension_format)
                        if render and (
                            render['thumb_size'] != tuple(preview.thumbnail_dimensions)
                            or render['thumb_format'] != preview.get_format('thumbnail')
                        ):
                            preview.sizes['thumbnail_format'] = render['thumb_format']
                            preview.sizes['thumbnail'] = render['thumb_size']
                            resize_image(
                                preview.image_path,
                                preview.thumbnail_path,
                                render['thumb_size'],
                                format=render['thumb_format'],
                                quality=35,
                            )
                            preview.save()

                    continue
                # else carry on with a full preview generation
            log.info('Recreating previews for theme: %s' % version.addon_id)
            xpi = get_filepath(version.file)
            theme_data = parse_addon(xpi, minimal=True).get('theme', {})
            generate_static_theme_preview.apply_async(
                args=(theme_data, version.id), queue='adhoc'
            )
        except OSError:
            pass
    index_addons.delay(addon_ids)


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
    log.info(
        '[%s@%s] %sDeleting addons starting at id: %s...'
        % (
            'Hard ' if with_deleted else '',
            len(addon_ids),
            delete_addons.rate_limit,
            addon_ids[0],
        )
    )
    addons = Addon.unfiltered.filter(pk__in=addon_ids).no_transforms()
    if with_deleted:
        with transaction.atomic():
            # Stop any of these guids from being reused
            addon_guids = list(addons.exclude(guid=None).values_list('guid', flat=True))
            denied = [
                DeniedGuid(guid=guid, comments='Hard deleted with delete_addons task')
                for guid in addon_guids
            ]
            DeniedGuid.objects.bulk_create(denied, ignore_conflicts=True)
            # Call QuerySet.delete rather than Addon.delete.
            addons.delete()
    else:
        for addon in addons:
            addon.delete(send_delete_email=False)


@task
@use_primary_db
def update_addon_hotness(averages):
    log.info('[%s] Updating add-ons hotness scores.', (len(averages)))

    averages = dict(averages)
    addons = (
        Addon.objects.filter(guid__in=averages.keys())
        .filter(status__in=amo.REVIEWED_STATUSES)
        .no_transforms()
    )

    for addon in addons:
        average = averages.get(addon.guid)

        # See: https://github.com/mozilla/addons-server/issues/15525
        if not average:
            log.error(
                'Averages not found for addon with id=%s and GUID=%s.',
                addon.id,
                addon.guid,
            )
            continue

        this = average['avg_this_week']
        three = average['avg_three_weeks_before']

        # Update the hotness score but only update hotness if necessary. We
        # don't want to cause unnecessary re-indexes.
        threshold = 250 if addon.type == amo.ADDON_STATICTHEME else 1000
        if this > threshold and three > 1:
            hotness = (this - three) / float(three)
            if addon.hotness != hotness:
                addon.update(hotness=hotness)
        else:
            if addon.hotness != 0:
                addon.update(hotness=0)


@task
def update_addon_weekly_downloads(data):
    log.info('[%s] Updating add-ons weekly downloads.', len(data))

    for hashed_guid, count in data:
        try:
            addon = Addon.objects.get(addonguid__hashed_guid=hashed_guid)
        except Addon.DoesNotExist:
            # The processing input comes from metrics which might be out of
            # date in regards to currently existing add-ons.
            log.info(
                'Got a weekly_downloads update (%s) but the add-on '
                "doesn't exist (hashed_guid=%s).",
                count,
                hashed_guid,
            )
            continue

        addon.update(weekly_downloads=int(float(count)))


@task
@set_modified_on
def resize_icon(source, dest_folder, target_sizes, **kw):
    """Resizes addon icons."""
    log.info('[1@None] Resizing icon: %s' % dest_folder)
    try:
        # Resize in every size we want.
        dest_file = None
        for size in target_sizes:
            dest_file = f'{dest_folder}-{size}.png'
            resize_image(source, dest_file, (size, size))

        # Store the original hash, we'll return it to update the corresponding
        # add-on. We only care about the first 8 chars of the md5, it's
        # unlikely a new icon on the same add-on would get the same first 8
        # chars, especially with icon changes being so rare in the first place.
        with open(source, 'rb') as fd:
            icon_hash = hashlib.md5(fd.read()).hexdigest()[:8]

        # Keep a copy of the original image.
        dest_file = '%s-original.png' % dest_folder
        os.rename(source, dest_file)

        return {'icon_hash': icon_hash}
    except Exception as e:
        log.error(f'Error saving addon icon ({dest_file}): {e}')


@task
@set_modified_on
def resize_preview(src, preview_pk, **kw):
    """Resizes preview images and stores the sizes on the preview."""
    preview = Preview.objects.get(pk=preview_pk)
    preview.sizes = {'thumbnail_format': amo.ADDON_PREVIEW_SIZES['thumbnail_format']}
    thumb_dst, full_dst, orig_dst = (
        preview.thumbnail_path,
        preview.image_path,
        preview.original_path,
    )
    log.info('[1@None] Resizing preview and storing size: %s' % thumb_dst)
    try:
        (preview.sizes['thumbnail'], preview.sizes['original']) = resize_image(
            src,
            thumb_dst,
            amo.ADDON_PREVIEW_SIZES['thumbnail'],
            format=amo.ADDON_PREVIEW_SIZES['thumbnail_format'],
        )
        (preview.sizes['image'], _) = resize_image(
            src,
            full_dst,
            amo.ADDON_PREVIEW_SIZES['full'],
        )
        if not os.path.exists(os.path.dirname(orig_dst)):
            os.makedirs(os.path.dirname(orig_dst))
        os.rename(src, orig_dst)
        preview.save()
        return True
    except Exception as e:
        log.error('Error saving preview: %s' % e)


@task
@use_primary_db
def disable_addons(addon_ids, **kw):
    """Set the given addon ids to disabled (amo.STATUS_DISABLED)."""
    log.info(
        '[%s@%s] Disabling addons starting at id: %s...'
        % (
            len(addon_ids),
            disable_addons.rate_limit,
            addon_ids[0],
        )
    )
    addons = Addon.unfiltered.filter(pk__in=addon_ids).no_transforms()
    for addon in addons:
        activity.log_create(amo.LOG.FORCE_DISABLE, addon, user=get_task_user())
    addons.update(status=amo.STATUS_DISABLED, _current_version=None)
    File.objects.filter(version__addon__in=addons).update(status=amo.STATUS_DISABLED)
    index_addons.delay(addon_ids)
