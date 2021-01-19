import hashlib
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import transaction
from django.utils.encoding import force_text

from elasticsearch_dsl import Search

import olympia.core

from olympia import amo
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
from olympia.amo.decorators import use_primary_db
from olympia.amo.storage_utils import copy_stored_file
from olympia.amo.utils import LocalFileStorage, extract_colors_from_image
from olympia.files.utils import get_filepath, parse_addon
from olympia.lib.es.utils import index_objects
from olympia.tags.models import Tag
from olympia.versions.models import generate_static_theme_preview, VersionPreview


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
            addon = Addon.unfiltered.get(guid=addon_guid)
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
    log.info('Indexing addons %s-%s. [%s]' % (ids[0], ids[-1], len(ids)))
    transforms = (attach_tags, attach_translations_dict)
    index_objects(
        ids,
        Addon,
        AddonIndexer.extract_document,
        kw.pop('index', None),
        transforms,
        Addon.unfiltered,
    )


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
        ids[0],
        ids[-1],
        length,
    )
    db_addons = Addon.unfiltered.in_bulk(ids)
    es_addons = (
        Search(
            doc_type=AddonIndexer.get_doctype_name(),
            index=AddonIndexer.get_index_alias(),
            using=amo.search.get_es(),
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
def add_dynamic_theme_tag(ids, **kw):
    """Add dynamic theme tag to addons with the specified ids."""
    log.info(
        'Adding  dynamic theme tag to addons %d-%d [%d].', ids[0], ids[-1], len(ids)
    )

    addons = Addon.objects.filter(id__in=ids)
    for addon in addons:
        files = addon.current_version.all_files
        if any('theme' in file_.permissions for file_ in files):
            Tag(tag_text='dynamic theme').save_tag(addon)
            index_addons.delay([addon.id])


@task
@use_primary_db
def extract_colors_from_static_themes(ids, **kw):
    """Extract and store colors from existing static themes."""
    log.info('Extracting static themes colors %d-%d [%d].', ids[0], ids[-1], len(ids))
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
    log.info(
        '[%s@%s] Recreating previews for themes starting at id: %s...'
        % (len(addon_ids), recreate_theme_previews.rate_limit, addon_ids[0])
    )
    addons = Addon.objects.filter(pk__in=addon_ids).no_transforms()
    only_missing = kw.get('only_missing', False)

    for addon in addons:
        version = addon.current_version
        if not version:
            continue
        try:
            if only_missing:
                with_size = (
                    VersionPreview.objects.filter(version=version)
                    .exclude(sizes={})
                    .count()
                )
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
def create_custom_icon_from_predefined(addon_ids, **kwargs):
    addons = Addon.objects.filter(id__in=addon_ids).no_transforms()
    hashes = {}

    predefined = os.path.join(settings.ROOT, 'static', 'img', 'addon-icons')
    _, icons = storage.listdir(predefined)
    for icon in icons:
        if b'32' in icon and b'default' not in icon:
            icon_name = force_text(icon.split(b'-')[0])
            with open(os.path.join(predefined, force_text(icon)), 'rb') as fd:
                hashes[icon_name] = hashlib.md5(fd.read()).hexdigest()[:8]

    for addon in addons:
        type_split = addon.icon_type.split('/') if addon.icon_type else []
        if len(type_split) != 2 or type_split[0] != 'icon':
            continue
        icon_name = type_split[1]

        destination = addon.get_icon_dir()
        for size in (32, 64, 128):
            src = os.path.join(predefined, f'{icon_name}-{size}.png')
            if not os.path.exists(src):
                break
            copy_stored_file(
                src,
                os.path.join(destination, f'{addon.id}-{size}.png'),
            )
        else:
            addon.update(icon_type='image/png', icon_hash=hashes.get(icon_name, ''))
