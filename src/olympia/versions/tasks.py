import itertools
import operator
import os
import tempfile
from io import BytesIO
from urllib.parse import urljoin

from django.conf import settings
from django.db import transaction
from django.template import loader
from django.urls import reverse

import requests
from django_statsd.clients import statsd
from PIL import Image

import olympia.core.logger
from olympia import amo
from olympia.activity.models import ActivityLog, VersionLog
from olympia.activity.utils import notify_about_activity_log
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import SafeStorage, extract_colors_from_image, pngcrush_image
from olympia.constants.blocklist import REASON_VERSION_DELETED
from olympia.devhub.tasks import resize_image
from olympia.files.models import File
from olympia.files.utils import get_background_images
from olympia.lib.crypto.tasks import duplicate_addon_version
from olympia.reviewers.models import NeedsHumanReview
from olympia.scanners.tasks import make_adapter_with_retry
from olympia.users.models import UserProfile
from olympia.users.utils import get_task_user
from olympia.versions.compare import VersionString
from olympia.versions.models import Version, VersionPreview

from .utils import (
    AdditionalBackground,
    convert_svg_to_png,
    encode_header,
    process_color_value,
    write_svg_to_png,
)


log = olympia.core.logger.getLogger('z.versions.task')


def _build_static_theme_preview_context(theme_manifest, file_):
    # First build the context shared by both the main preview and the thumb
    context = {'amo': amo}
    context.update(
        dict(
            process_color_value(prop, color)
            for prop, color in theme_manifest.get('colors', {}).items()
        )
    )
    images_dict = theme_manifest.get('images', {})
    header_url = images_dict.get('theme_frame', images_dict.get('headerURL', ''))
    file_ext = os.path.splitext(header_url)[1]
    backgrounds = get_background_images(file_, theme_manifest)
    header_src, header_width, header_height = encode_header(
        backgrounds.get(header_url), file_ext
    )
    context.update(
        header_src=header_src,
        header_src_height=header_height,
        header_width=header_width,
    )
    # Limit the srcs rendered to 15 to ameliorate DOSing somewhat.
    # https://bugzilla.mozilla.org/show_bug.cgi?id=1435191 for background.
    additional_srcs = images_dict.get('additional_backgrounds', [])[:15]
    additional_alignments = theme_manifest.get('properties', {}).get(
        'additional_backgrounds_alignment', []
    )
    additional_tiling = theme_manifest.get('properties', {}).get(
        'additional_backgrounds_tiling', []
    )
    additional_backgrounds = [
        AdditionalBackground(path, alignment, tiling, backgrounds.get(path))
        for (path, alignment, tiling) in itertools.zip_longest(
            additional_srcs, additional_alignments, additional_tiling
        )
        if path is not None
    ]
    context.update(additional_backgrounds=additional_backgrounds)
    return context


UI_FIELDS = (
    'toolbar',
    'tab_selected',
    'tab_line',
    'bookmark_text',
    'tab_background_text',
    'toolbar_field',
    'toolbar_field_text',
    'icons',
)
TRANSPARENT_UI = {field: 'rgb(0,0,0,0)' for field in UI_FIELDS}


def render_to_svg(template, context, preview, thumbnail_dimensions, theme_manifest):
    tmp_args = {
        'dir': settings.TMP_PATH,
        'mode': 'wb',
        'delete': not settings.DEBUG,
        'suffix': '.png',
    }

    # first stage - just the images
    image_only_svg = template.render(context).encode('utf-8')

    with BytesIO() as background_blob:
        # write the image only background to a file and back to a blob
        with tempfile.NamedTemporaryFile(**tmp_args) as background_png:
            if not write_svg_to_png(image_only_svg, background_png.name):
                return
            # TODO: improvement - only re-encode jpg backgrounds as jpg?
            Image.open(background_png.name).convert('RGB').save(
                background_blob, 'JPEG', quality=80
            )

        # and encode the image in base64 to use in the context
        try:
            header_src, _, _ = encode_header(background_blob.getvalue(), 'jpg')
        except Exception as exc:
            log.info('Exception during svg preview generation %s', exc)
            return

    # then rebuild a context with it and render
    with_ui_context = {
        **dict(
            process_color_value(prop, color)
            for prop, color in theme_manifest.get('colors', {}).items()
        ),
        'amo': amo,
        'header_src': header_src,
        'svg_render_size': context['svg_render_size'],
        'header_src_height': context['svg_render_size'].height,
        'header_width': context['svg_render_size'].width,
    }
    finished_svg = template.render(with_ui_context).encode('utf-8')

    # and write that svg to preview.image_path
    storage = SafeStorage(
        root_setting='MEDIA_ROOT', rel_location=VersionPreview.media_folder
    )
    with storage.open(preview.image_path, 'wb') as image_path:
        image_path.write(finished_svg)

    # then also write a fully rendered svg and resize for the thumbnails
    with tempfile.NamedTemporaryFile(**tmp_args) as complete_preview_as_png:
        if convert_svg_to_png(preview.image_path, complete_preview_as_png.name):
            resize_image(
                complete_preview_as_png.name,
                preview.thumbnail_path,
                thumbnail_dimensions,
                format=preview.get_format('thumbnail'),
                quality=35,  # It's ignored for png format, so it's fine to always set.
            )
            return True


def render_to_png(template, context, preview, thumbnail_dimensions):
    svg = template.render(context).encode('utf-8')
    if write_svg_to_png(svg, preview.image_path):
        resize_image(
            preview.image_path,
            preview.thumbnail_path,
            thumbnail_dimensions,
            format=preview.get_format('thumbnail'),
            quality=35,  # It's ignored for png format, so it's fine to always set.
        )
        pngcrush_image(preview.image_path)
        return True


@task
@use_primary_db
def generate_static_theme_preview(theme_manifest, version_pk):
    # Make sure we import `index_addons` late in the game to avoid having
    # a "copy" of it here that won't get mocked by our ESTestCase
    from olympia.addons.tasks import index_addons

    tmpl = loader.get_template('devhub/addons/includes/static_theme_preview_svg.xml')
    file_ = File.objects.filter(version_id=version_pk).first()
    if not file_:
        return
    complete_context = _build_static_theme_preview_context(theme_manifest, file_)
    renderings = sorted(
        amo.THEME_PREVIEW_RENDERINGS.values(), key=operator.itemgetter('position')
    )
    colors = None
    old_preview_ids = list(
        VersionPreview.objects.filter(version_id=version_pk).values_list(
            'id', flat=True
        )
    )
    for rendering in renderings:
        # Create a Preview for this rendering.
        preview = VersionPreview.objects.create(
            version_id=version_pk,
            position=rendering['position'],
            sizes={
                'image_format': rendering['image_format'],
                'thumbnail_format': rendering['thumbnail_format'],
            },
        )

        # Add the size to the context and render
        complete_context.update(svg_render_size=rendering['full'])
        if rendering['image_format'] == 'svg':
            render_success = render_to_svg(
                tmpl,
                {**complete_context, **TRANSPARENT_UI},
                preview,
                rendering['thumbnail'],
                theme_manifest,
            )
        else:
            render_success = render_to_png(
                tmpl, complete_context, preview, rendering['thumbnail']
            )
        if render_success:
            # Extract colors once and store it for all previews.
            # Use the thumbnail for extra speed, we don't need to be super accurate.
            if colors is None:
                colors = extract_colors_from_image(preview.thumbnail_path)
            data = {
                'sizes': {
                    'image': rendering['full'],
                    'thumbnail': rendering['thumbnail'],
                    'image_format': rendering['image_format'],
                    'thumbnail_format': rendering['thumbnail_format'],
                },
                'colors': colors,
            }
            preview.update(**data)
    VersionPreview.objects.filter(id__in=old_preview_ids).delete()
    addon_id = Version.objects.values_list('addon_id', flat=True).get(id=version_pk)
    index_addons.delay([addon_id])


@task
def delete_preview_files(pk, **kw):
    VersionPreview.delete_preview_files(
        sender=None, instance=VersionPreview.objects.get(pk=pk)
    )


@task
@use_primary_db
def delete_list_theme_previews(addon_ids, **kw):
    # Make sure we import `index_addons` late in the game to avoid having
    # a "copy" of it here that won't get mocked by our ESTestCase
    from olympia.addons.tasks import index_addons

    log.info(
        '[%s@%s] Deleting preview sizes for themes starting at id: %s...'
        % (len(addon_ids), delete_list_theme_previews.rate_limit, addon_ids[0])
    )
    for addon_id in addon_ids:
        log.info('Deleting "list" size previews for theme: %s' % addon_id)
        VersionPreview.objects.filter(
            version__addon_id=addon_id, sizes__image=[760, 92]
        ).delete()

    index_addons.delay(addon_ids)


@task
@use_primary_db
def hard_delete_versions(version_ids, **kw):
    """Hard delete the given versions by id."""
    log.info(
        '[%s@%s] Hard deleting versions starting at id: %s...'
        % (
            len(version_ids),
            hard_delete_versions.rate_limit,
            version_ids[0],
        )
    )
    versions = Version.unfiltered.filter(pk__in=version_ids).no_transforms()
    for version in versions:
        with transaction.atomic():
            version.delete(hard=True)


@task
@use_primary_db
def duplicate_addon_version_for_rollback(
    *, version_pk, new_version_number, user_pk, notes
):
    task_user = get_task_user()
    new_version_number = VersionString(new_version_number)
    old_version = Version.unfiltered.get(id=version_pk)
    user = UserProfile.objects.get(id=user_pk)
    rollback_from_reviewed_to_unreviewed = (
        old_version.human_review_date is None
        and (
            latest_version := old_version.addon.find_latest_version(
                old_version.channel,
                exclude=(amo.STATUS_AWAITING_REVIEW, amo.STATUS_DISABLED),
            )
        )
        and latest_version.human_review_date is not None
    )

    text = (
        f'Rolling back add-on "{old_version.addon}", to version "{old_version.version}"'
    )
    log.info(f'Starting: {text}')
    version = duplicate_addon_version(old_version, new_version_number, user)
    if not version:
        log_entry = ActivityLog.objects.create(
            amo.LOG.VERSION_ROLLBACK_FAILED,
            old_version.addon,
            old_version,
            user=task_user,
            details={
                # The comment is not translated on purpose, to behave like regular human
                # approval does.
                'comments': f'{text} failed.\n'
                'Please create and submit a new version manually.'
            },
        )
        version = old_version
        statsd.incr('versions.tasks.rollback.failure')
    else:
        version.human_review_date = old_version.human_review_date
        if notes is not None:
            version.release_notes = notes
        version.save()
        if old_version.source:
            version.source.save(
                os.path.basename(old_version.source.name), old_version.source.file
            )
            version.save(update_fields=('source',))

        # associate all activity from old_version to new_version
        VersionLog.objects.bulk_create(
            VersionLog(version=version, activity_log=vl.activity_log)
            for vl in VersionLog.objects.filter(version=old_version)
        )

        # Now log and notify the developers of that add-on.
        # Any exception should have caused an early return before reaching this point.
        log_entry = ActivityLog.objects.create(
            amo.LOG.VERSION_ROLLBACK,
            version.addon,
            version,
            old_version.version,
            user=task_user,
            details={
                # The comment is not translated on purpose, to behave like regular human
                # approval does.
                'comments': f'{text} by re-publishing as "{new_version_number}" '
                'successful!\n'
                'Users with auto-update enabled will be automatically upgraded to this '
                'version. Keep in mind that, like any submission, reviewers may look '
                'into this version in the future and determine that it requires '
                'changes or should be taken down.\r\n'
                '\r\n'
                'Thank you!'
            },
        )
        VersionLog.objects.create(activity_log=log_entry, version=old_version)
        if rollback_from_reviewed_to_unreviewed:
            NeedsHumanReview.objects.create(
                version=version, reason=NeedsHumanReview.REASONS.VERSION_ROLLBACK
            )
        statsd.incr('versions.tasks.rollback.success')

    notify_about_activity_log(
        version.addon, version, log_entry, perm_setting='individual_contact'
    )


@task
@use_primary_db
def soft_block_versions(version_ids, reason=REASON_VERSION_DELETED, **kw):
    """Soft-blocks the specified add-on versions - used for after deletes"""
    # To avoid circular imports
    from olympia.blocklist.models import BlocklistSubmission, BlockType
    from olympia.blocklist.utils import save_versions_to_blocks

    try:
        task_user = get_task_user()
    except UserProfile.DoesNotExist:
        log.info('Task user does not exist so we are running in a test, abort blocking')
        return

    # Requery the ids to check they're valid, and we don't soften an existing hard-block
    versions = list(
        Version.unfiltered.filter(
            pk__in=version_ids, blockversion__id=None
        ).values_list('addon__guid', 'id', named=True)
    )
    log.info(
        '[%s@%s] Soft blocking deleted versions from id %s to id %s...'
        % (
            len(versions),
            soft_block_versions.rate_limit,
            version_ids[0],
            version_ids[-1],
        )
    )

    save_versions_to_blocks(
        {version.addon__guid for version in versions},
        BlocklistSubmission(
            block_type=BlockType.SOFT_BLOCKED,
            updated_by=task_user,
            reason=reason,
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.PUBLISHED,
            changed_version_ids=[ver.id for ver in versions],
            # Either addon is already deleted, so this is redundant,
            # or we're deleting single versions.
            disable_addon=False,
        ),
        overwrite_block_metadata=False,
    )


@task
def call_source_builder(version_pk, activity_log_id):
    log.info(
        'Calling source builder API for Version %s (activity_log_id = %s)',
        version_pk,
        activity_log_id,
    )

    try:
        version = Version.objects.get(pk=version_pk)

        with requests.Session() as http:
            adapter = make_adapter_with_retry()
            http.mount('http://', adapter)
            http.mount('https://', adapter)

            json_payload = {
                'addon_id': version.addon_id,
                'version_id': version.id,
                'download_source_url': urljoin(
                    settings.EXTERNAL_SITE_URL,
                    reverse('downloads.source', kwargs={'version_id': version.id}),
                ),
                'license_slug': version.license.slug,
                'activity_log_id': activity_log_id,
            }
            http.post(
                url=settings.SOURCE_BUILDER_API_URL,
                json=json_payload,
                timeout=settings.SOURCE_BUILDER_API_TIMEOUT,
            )
    except Exception:
        log.exception(
            'Error while calling source builder API for Version %s '
            '(activity_log_id = %s)',
            version_pk,
            activity_log_id,
        )
