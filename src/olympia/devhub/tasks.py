# -*- coding: utf-8 -*-
import datetime
import hashlib
import json
import os
import subprocess
import tempfile

from copy import deepcopy
from decimal import Decimal
from functools import wraps
from zipfile import BadZipfile

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django.core.validators import ValidationError
from django.db import transaction
from django.template import loader
from django.utils.encoding import force_text
from django.utils.translation import ugettext

from celery.result import AsyncResult
from django_statsd.clients import statsd

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon, Persona, Preview
from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on, use_primary_db
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import (
    image_size, pngcrush_image, resize_image, send_html_mail_jinja, send_mail,
    utc_millesecs_from_epoch)
from olympia.api.models import SYMMETRIC_JWT_TYPE, APIKey
from olympia.lib.akismet.models import AkismetReport
from olympia.files.models import File, FileUpload, FileValidation
from olympia.files.utils import (
    InvalidManifest, NoManifestFound, parse_addon, SafeZip,
    UnsupportedFileType)
from olympia.files.tasks import repack_fileupload
from olympia.versions.models import Version
from olympia.devhub import file_validation_annotations as annotations


log = olympia.core.logger.getLogger('z.devhub.task')


def validate(file_, listed=None, subtask=None, synchronous=False,
             pretask=None):
    """Run the validator on the given File or FileUpload object. If a task has
    already begun for this file, instead return an AsyncResult object for that
    task.

    file_ can be either a File or FileUpload; if File then listed must be
    None; if FileUpload listed must be specified."""

    # Import loop.
    from .utils import Validator

    validator = Validator(file_, listed=listed)

    task_id = cache.get(validator.cache_key)

    if not synchronous and task_id:
        return AsyncResult(task_id)
    else:
        # Note: pretask should never have ignore_result=False, as passing a
        # result this would modify the arguments expected by the tasks
        # afterwards and that would make @validation_task fail with mismatched
        # arguments.
        task = validator.get_task()
        chain = task if pretask is None else pretask | task
        if subtask is not None:
            chain |= subtask

        if synchronous:
            result = chain.apply()
        else:
            result = chain.delay()

            cache.set(validator.cache_key, result.task_id, 5 * 60)

        return result


def validate_and_submit(addon, file_, channel, pretask=None):
    return validate(
        file_, listed=(channel == amo.RELEASE_CHANNEL_LISTED),
        subtask=submit_file.si(addon.pk, file_.pk, channel), pretask=pretask)


@task
@use_primary_db
def submit_file(addon_pk, upload_pk, channel):
    addon = Addon.unfiltered.get(pk=addon_pk)
    upload = FileUpload.objects.get(pk=upload_pk)
    if upload.passed_all_validations:
        create_version_for_upload(addon, upload, channel)
    else:
        log.info('Skipping version creation for {upload_uuid} that failed '
                 'validation'.format(upload_uuid=upload.uuid))


@transaction.atomic
def create_version_for_upload(addon, upload, channel):
    """Note this function is only used for API uploads."""
    fileupload_exists = addon.fileupload_set.filter(
        created__gt=upload.created, version=upload.version).exists()
    version_exists = Version.unfiltered.filter(
        addon=addon, version=upload.version).exists()
    if (fileupload_exists or version_exists):
        log.info('Skipping Version creation for {upload_uuid} that would '
                 ' cause duplicate version'.format(upload_uuid=upload.uuid))
    else:
        # Import loop.
        from olympia.devhub.utils import add_dynamic_theme_tag
        from olympia.devhub.views import auto_sign_version

        log.info('Creating version for {upload_uuid} that passed '
                 'validation'.format(upload_uuid=upload.uuid))
        # Note: if we somehow managed to get here with an invalid add-on,
        # parse_addon() will raise ValidationError and the task will fail
        # loudly in sentry.
        parsed_data = parse_addon(upload, addon, user=upload.user)
        version = Version.from_upload(
            upload, addon, [x[0] for x in amo.APPS_CHOICES],
            channel,
            parsed_data=parsed_data)
        # The add-on's status will be STATUS_NULL when its first version is
        # created because the version has no files when it gets added and it
        # gets flagged as invalid. We need to manually set the status.
        if (addon.status == amo.STATUS_NULL and
                channel == amo.RELEASE_CHANNEL_LISTED):
            addon.update(status=amo.STATUS_NOMINATED)
        auto_sign_version(version)
        add_dynamic_theme_tag(version)


def validation_task(fn):
    """Wrap a validation task so that it runs with the correct flags, then
    parse and annotate the results before returning."""

    @task(bind=True, ignore_result=False,  # We want to pass the results down.
          soft_time_limit=settings.VALIDATOR_TIMEOUT)
    @wraps(fn)
    def wrapper(task, id_or_path, *args, **kwargs):
        # This is necessary to prevent timeout exceptions from being set
        # as our result, and replacing the partial validation results we'd
        # prefer to return.
        task.ignore_result = True
        try:
            data = fn(id_or_path, **kwargs)
            results = json.loads(force_text(data))
            return results
        except UnsupportedFileType as exc:
            results = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
            annotations.insert_validation_message(
                results, type_='error',
                message=exc.message, msg_id='unsupported_filetype')
            return results
        except BadZipfile:
            results = deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT)
            annotations.insert_validation_message(
                results, type_='error',
                message=ugettext('Invalid or corrupt add-on file.'))
            return results
        except Exception as exc:
            log.exception('Unhandled error during validation: %r' % exc)
            results = deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT)
            return results
        finally:
            # But we do want to return the results after that exception has
            # been handled.
            task.ignore_result = False
    return wrapper


@validation_task
@use_primary_db
def validate_upload(upload_pk, channel):
    """
    Repack and then validate a FileUpload.

    This only exists to get repack_fileupload() and validate_file_path()
    into a single task that is wrapped by @validation_task. We do this because
    with Celery < 4.2, on_error is never executed for task chains, so we use
    a task decorated by @validation_task which takes care of it for us. Once
    we upgrade to Celery 4.2, we stop calling repack_fileupload() here and just
    have Validator.task return a chain with those 2 tasks when it's dealing
    with a FileUpload.
    https://github.com/mozilla/addons-server/issues/9068#issuecomment-473255011
    """
    upload = FileUpload.objects.get(pk=upload_pk)
    repack_fileupload(upload.pk)
    return validate_file_path(upload.path, channel)


def validate_file_path(path, channel):
    """Run the validator against a file at the given path, and return the
    results, which should be a json string.

    Should only be called directly by `validate_upload` or `validate_file`
    tasks.

    Search plugins don't call the linter but get linted by
    `annotate_search_plugin_validation`.

    All legacy extensions (including dictionaries, themes etc) are disabled
    via `annotate_legacy_addon_restrictions` except if they're signed by
    Mozilla.
    """
    if path.endswith('.xml'):
        # search plugins are validated directly by addons-server
        # so that we don't have to call the linter or validator
        results = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
        annotations.annotate_search_plugin_validation(
            results=results, file_path=path, channel=channel)
        return json.dumps(results)

    # Annotate results with potential legacy add-ons restrictions.
    try:
        data = parse_addon(path, minimal=True)
    except NoManifestFound:
        # If no manifest is found, return empty data; the check below
        # explicitly looks for is_webextension is False, so it will not be
        # considered a legacy extension, and the linter will pick it up and
        # will know what message to return to the developer.
        data = {}
    except InvalidManifest:
        # Similarly, if we can't parse the manifest, let the linter pick that
        # up.
        data = {}
    is_legacy_extension = data.get('is_webextension', None) is False
    is_mozilla_signed = data.get('is_mozilla_signed_extension', None) is True

    if is_legacy_extension:
        results = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
        annotations.annotate_legacy_addon_restrictions(
            path=path, results=results, parsed_data=data,
            error=not is_mozilla_signed)
        return json.dumps(results)
    return run_addons_linter(path, channel=channel)


@validation_task
def validate_file(file_id):
    """Validate a File instance. If cached validation results exist, return
    those, otherwise run the validator.

    Should only be called directly by Validator."""

    file_ = File.objects.get(pk=file_id)
    try:
        return file_.validation.validation
    except FileValidation.DoesNotExist:
        return validate_file_path(
            file_.current_file_path, file_.version.channel)


@task
@use_primary_db
def handle_upload_validation_result(
        results, upload_pk, channel, is_mozilla_signed):
    """Annotate a set of validation results and save them to the given
    FileUpload instance."""
    upload = FileUpload.objects.get(pk=upload_pk)

    # Check for API keys in submissions.
    # Make sure it is extension-like, e.g. no LWT or search plugin
    try:
        results = check_for_api_keys_in_file(results=results, upload=upload)
    except (ValidationError, BadZipfile, IOError):
        pass

    # Annotate results with akismet reports results if there are any.
    reports = AkismetReport.objects.filter(upload_instance=upload)
    akismet_results = [
        (report.comment_type, report.result) for report in reports]
    annotations.annotate_akismet_spam_check(results, akismet_results)

    # Annotate results with potential webext warnings on new versions.
    if upload.addon_id and upload.version:
        annotations.annotate_webext_incompatibilities(
            results=results, file_=None, addon=upload.addon,
            version_string=upload.version, channel=channel)

    upload.validation = json.dumps(results)
    upload.save()  # We want to hit the custom save().

    # Track the time it took from first upload through validation
    # until the results were processed and saved.
    upload_start = utc_millesecs_from_epoch(upload.created)
    now = datetime.datetime.now()
    now_ts = utc_millesecs_from_epoch(now)
    delta = now_ts - upload_start
    statsd.timing('devhub.validation_results_processed', delta)

    if not storage.exists(upload.path):
        # TODO: actually fix this so we can get stats. It seems that
        # the file maybe gets moved but it needs more investigation.
        log.warning('Scaled upload stats were not tracked. File is '
                    'missing: {}'.format(upload.path))
        return

    size = Decimal(storage.size(upload.path))
    megabyte = Decimal(1024 * 1024)

    # Stash separate metrics for small / large files.
    quantifier = 'over' if size > megabyte else 'under'
    statsd.timing(
        'devhub.validation_results_processed_{}_1mb'.format(quantifier), delta)

    # Scale the upload / processing time by package size (in MB)
    # so we can normalize large XPIs which naturally take longer to validate.
    scaled_delta = None
    size_in_mb = size / megabyte
    if size > 0:
        # If the package is smaller than 1MB, don't scale it. This should
        # help account for validator setup time.
        unit = size_in_mb if size > megabyte else Decimal(1)
        scaled_delta = Decimal(delta) / unit
        statsd.timing('devhub.validation_results_processed_per_mb',
                      scaled_delta)

    log.info('Time to process and save upload validation; '
             'upload.pk={upload}; processing_time={delta}; '
             'scaled_per_mb={scaled}; upload_size_in_mb={size_in_mb}; '
             'created={created}; now={now}'
             .format(delta=delta, upload=upload.pk,
                     created=upload.created, now=now,
                     scaled=scaled_delta, size_in_mb=size_in_mb))


# We need to explicitly not ignore the result, for the sake of `views.py` code
# that needs to wait on a result, rather than just trigger the task to save
# the result to a FileValidation object.
@task(ignore_result=False)
@use_primary_db
def handle_file_validation_result(results, file_id, *args):
    """Annotate a set of validation results and save them to the given File
    instance."""

    file_ = File.objects.get(pk=file_id)

    annotations.annotate_webext_incompatibilities(
        results=results, file_=file_, addon=file_.version.addon,
        version_string=file_.version.version, channel=file_.version.channel)

    return FileValidation.from_json(file_, results).pk


def check_for_api_keys_in_file(results, upload):
    if upload.addon:
        users = upload.addon.authors.all()
    else:
        users = [upload.user] if upload.user else []

    keys = []
    for user in users:
        try:
            key = APIKey.get_jwt_key(user_id=user.id)
            keys.append(key)
        except APIKey.DoesNotExist:
            pass

    if len(keys) > 0:
        zipfile = SafeZip(source=upload.path)
        for zipinfo in zipfile.info_list:
            if zipinfo.file_size >= 64:
                file_ = zipfile.read(zipinfo)
                for key in keys:
                    if key.secret in file_.decode(errors="ignore"):
                        log.info('Developer API key for user %s found in '
                                 'submission.' % key.user)
                        if key.user == upload.user:
                            msg = ugettext('Your developer API key was found '
                                           'in the submitted file. To protect '
                                           'your account, the key will be '
                                           'revoked.')
                        else:
                            msg = ugettext('The developer API key of a '
                                           'coauthor was found in the '
                                           'submitted file. To protect your '
                                           'add-on, the key will be revoked.')
                        annotations.insert_validation_message(
                            results, type_='error',
                            message=msg, msg_id='api_key_detected',
                            compatibility_type=None)

                        # Revoke after 2 minutes to allow the developer to
                        # fetch the validation results
                        revoke_api_key.apply_async(
                            kwargs={'key_id': key.id}, countdown=120)
        zipfile.close()

    return results


@task
@use_primary_db
def revoke_api_key(key_id):
    try:
        # Fetch the original key, do not use `get_jwt_key`
        # so we get access to a user object for logging later.
        original_key = APIKey.objects.get(
            type=SYMMETRIC_JWT_TYPE, id=key_id)
        # Fetch the current key to compare to the original,
        # throws if the key has been revoked, which also means
        # `original_key` is not active.
        current_key = APIKey.get_jwt_key(user_id=original_key.user.id)
        if current_key.key != original_key.key:
            log.info('User %s has already regenerated the key, nothing to be '
                     'done.' % original_key.user)
        else:
            with transaction.atomic():
                log.info('Revoking key for user %s.' % current_key.user)
                current_key.update(is_active=None)
                send_api_key_revocation_email(emails=[current_key.user.email])
    except APIKey.DoesNotExist:
        log.info('User %s has already revoked the key, nothing to be done.'
                 % original_key.user)
        pass


def run_addons_linter(path, channel):
    from .utils import fix_addons_linter_output

    args = [
        settings.ADDONS_LINTER_BIN,
        path,
        '--boring',
        '--output=json'
    ]

    if channel == amo.RELEASE_CHANNEL_UNLISTED:
        args.append('--self-hosted')

    if not os.path.exists(path):
        raise ValueError(
            'Path "{}" is not a file or directory or does not exist.'
            .format(path))

    stdout, stderr = (
        tempfile.TemporaryFile(),
        tempfile.TemporaryFile())

    with statsd.timer('devhub.linter'):
        process = subprocess.Popen(
            args,
            stdout=stdout,
            stderr=stderr,
            # default but explicitly set to make sure we don't open a shell.
            shell=False
        )

        process.wait()

        stdout.seek(0)
        stderr.seek(0)

        output, error = stdout.read(), stderr.read()

        # Make sure we close all descriptors, otherwise they'll hang around
        # and could cause a nasty exception.
        stdout.close()
        stderr.close()

    if error:
        raise ValueError(error)

    parsed_data = json.loads(force_text(output))

    result = json.dumps(fix_addons_linter_output(parsed_data, channel))
    track_validation_stats(result)

    return result


def track_validation_stats(json_result):
    """
    Given a raw JSON string of validator results, log some stats.
    """
    result = json.loads(force_text(json_result))
    result_kind = 'success' if result['errors'] == 0 else 'failure'
    statsd.incr('devhub.linter.results.all.{}'.format(result_kind))

    listed_tag = 'listed' if result['metadata']['listed'] else 'unlisted'

    # Track listed/unlisted success/fail.
    statsd.incr('devhub.linter.results.{}.{}'
                .format(listed_tag, result_kind))


@task
@use_primary_db
@set_modified_on
def pngcrush_existing_icons(addon_id):
    """
    Call pngcrush_image() on the icons of a given add-on.
    """
    log.info('Crushing icons for add-on %s', addon_id)
    addon = Addon.objects.get(pk=addon_id)
    if addon.icon_type != 'image/png':
        log.info('Aborting icon crush for add-on %s, icon type is not a PNG.',
                 addon_id)
        return
    icon_dir = addon.get_icon_dir()
    pngcrush_image(os.path.join(icon_dir, '%s-64.png' % addon_id))
    pngcrush_image(os.path.join(icon_dir, '%s-32.png' % addon_id))
    # Return an icon hash that set_modified_on decorator will set on the add-on
    # after a small delay. This is normally done with the true md5 hash of the
    # original icon, but we don't necessarily have it here. We could read one
    # of the icons we modified but it does not matter just fake a hash to
    # indicate it was "manually" crushed.
    return {
        'icon_hash': 'mcrushed'
    }


@task
@use_primary_db
@set_modified_on
def pngcrush_existing_preview(preview_id):
    """
    Call pngcrush_image() on the images of a given add-on Preview object.
    """
    log.info('Crushing images for Preview %s', preview_id)
    preview = Preview.objects.get(pk=preview_id)
    pngcrush_image(preview.thumbnail_path)
    pngcrush_image(preview.image_path)
    # We don't need a hash, previews are cachebusted with their modified date,
    # which does not change often. @set_modified_on will do that for us
    # automatically if the task was called with set_modified_on_obj=[preview].


@task
@use_primary_db
@set_modified_on
def pngcrush_existing_theme(persona_id):
    """
    Call pngcrush_image() on the images of a given Persona object.
    """
    log.info('Crushing images for Persona %s', persona_id)
    persona = Persona.objects.get(pk=persona_id)
    # Only do this on "new" Personas with persona_id = 0, the older ones (with
    # a persona_id) have jpeg and not pngs.
    if not persona.is_new():
        log.info('Aborting images crush for Persona %s (too old).', persona_id)
        return
    pngcrush_image(persona.preview_path)
    # No need to crush thumb_path, it's the same as preview_path for "new"
    # Personas.
    pngcrush_image(persona.icon_path)
    if persona.header:
        pngcrush_image(persona.header_path)
    if persona.footer:
        pngcrush_image(persona.footer_path)


@task
@set_modified_on
def resize_icon(source, dest_folder, target_sizes, **kw):
    """Resizes addon icons."""
    log.info('[1@None] Resizing icon: %s' % dest_folder)
    try:
        # Resize in every size we want.
        dest_file = None
        for size in target_sizes:
            dest_file = '%s-%s.png' % (dest_folder, size)
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

        return {
            'icon_hash': icon_hash
        }
    except Exception as e:
        log.error("Error saving addon icon (%s): %s" % (dest_file, e))


@task
@set_modified_on
def resize_preview(src, preview_pk, **kw):
    """Resizes preview images and stores the sizes on the preview."""
    preview = Preview.objects.get(pk=preview_pk)
    thumb_dst, full_dst, orig_dst = (
        preview.thumbnail_path, preview.image_path, preview.original_path)
    sizes = {}
    log.info('[1@None] Resizing preview and storing size: %s' % thumb_dst)
    try:
        (sizes['thumbnail'], sizes['original']) = resize_image(
            src, thumb_dst, amo.ADDON_PREVIEW_SIZES['thumb'])
        (sizes['image'], _) = resize_image(
            src, full_dst, amo.ADDON_PREVIEW_SIZES['full'])
        if not os.path.exists(os.path.dirname(orig_dst)):
            os.makedirs(os.path.dirname(orig_dst))
        os.rename(src, orig_dst)
        preview.sizes = sizes
        preview.save()
        return True
    except Exception as e:
        log.error("Error saving preview: %s" % e)


def _recreate_images_for_preview(preview):
    log.info('Resizing preview: %s' % preview.id)
    try:
        preview.sizes = {}
        if storage.exists(preview.original_path):
            # We have an original size image, so we can resize that.
            src = preview.original_path
            preview.sizes['image'], preview.sizes['original'] = resize_image(
                src, preview.image_path, amo.ADDON_PREVIEW_SIZES['full'])
            preview.sizes['thumbnail'], _ = resize_image(
                src, preview.thumbnail_path, amo.ADDON_PREVIEW_SIZES['thumb'])
        else:
            # Otherwise we can't create a new sized full image, but can
            # use it for a new thumbnail
            src = preview.image_path
            preview.sizes['thumbnail'], preview.sizes['image'] = resize_image(
                src, preview.thumbnail_path, amo.ADDON_PREVIEW_SIZES['thumb'])
        preview.save()
        return True
    except Exception as e:
        log.exception("Error saving preview: %s" % e)


@task
@use_primary_db
def recreate_previews(addon_ids, **kw):
    log.info('[%s@%s] Getting preview sizes for addons starting at id: %s...'
             % (len(addon_ids), recreate_previews.rate_limit, addon_ids[0]))
    addons = Addon.objects.filter(pk__in=addon_ids).no_transforms()

    for addon in addons:
        log.info('Recreating previews for addon: %s' % addon.id)
        previews = addon.previews.all()
        for preview in previews:
            _recreate_images_for_preview(preview)


@task
@use_primary_db
def get_preview_sizes(ids, **kw):
    log.info('[%s@%s] Getting preview sizes for addons starting at id: %s...'
             % (len(ids), get_preview_sizes.rate_limit, ids[0]))
    addons = Addon.objects.filter(pk__in=ids).no_transforms()

    for addon in addons:
        previews = addon.previews.all()
        log.info('Found %s previews for: %s' % (previews.count(), addon.pk))
        for preview in previews:
            try:
                log.info('Getting size for preview: %s' % preview.pk)
                sizes = {
                    'thumbnail': image_size(preview.thumbnail_path),
                    'image': image_size(preview.image_path),
                }
                preview.update(sizes=sizes)
            except Exception as err:
                log.error('Failed to find size of preview: %s, error: %s'
                          % (addon.pk, err))


def failed_validation(*messages):
    """Return a validation object that looks like the add-on validator."""
    m = []
    for msg in messages:
        m.append({'type': 'error', 'message': msg, 'tier': 1})

    return json.dumps({'errors': 1, 'success': False, 'messages': m})


def check_content_type(response, content_type,
                       no_ct_message, wrong_ct_message):
    if not response.headers.get('Content-Type', '').startswith(content_type):
        if 'Content-Type' in response.headers:
            raise Exception(wrong_ct_message %
                            (content_type, response.headers['Content-Type']))
        else:
            raise Exception(no_ct_message % content_type)


def get_content_and_check_size(response, max_size, error_message):
    # Read one extra byte. Reject if it's too big so we don't have issues
    # downloading huge files.
    content = response.read(max_size + 1)
    if len(content) > max_size:
        raise Exception(error_message % max_size)
    return content


@task
def send_welcome_email(addon_pk, emails, context, **kw):
    log.info(u'[1@None] Sending welcome email for %s to %s.' %
             (addon_pk, emails))
    subject = (
        u'Mozilla Add-ons: %s has been submitted to addons.mozilla.org!' %
        context.get('addon_name', 'Your add-on'))
    html_template = 'devhub/email/submission.html'
    text_template = 'devhub/email/submission.txt'
    return send_html_mail_jinja(subject, html_template, text_template,
                                context, recipient_list=emails,
                                from_email=settings.ADDONS_EMAIL,
                                use_deny_list=False,
                                perm_setting='individual_contact')


def send_api_key_revocation_email(emails):
    log.info(u'[1@None] Sending API key revocation email to %s.' % emails)
    subject = ugettext(
        u'Mozilla Security Notice: Your AMO API credentials have been revoked')
    template = loader.get_template(
        'devhub/email/submission_api_key_revocation.txt')
    context = {
        'api_keys_url': reverse('devhub.api_key')
    }
    send_mail(subject, template.render(context),
              from_email=settings.ADDONS_EMAIL,
              recipient_list=emails,
              use_deny_list=False,
              perm_setting='individual_contact')
