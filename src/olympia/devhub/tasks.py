import datetime
import json
import os
import subprocess
import tempfile
from copy import deepcopy
from decimal import Decimal
from functools import wraps
from zipfile import BadZipFile

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.validators import ValidationError
from django.db import transaction
from django.template import loader
from django.urls import reverse
from django.utils.encoding import force_str
from django.utils.translation import gettext

import waffle
from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.reverse import override_url_prefix
from olympia.amo.utils import (
    image_size,
    resize_image,
    send_html_mail_jinja,
    send_mail,
    utc_millesecs_from_epoch,
)
from olympia.api.models import SYMMETRIC_JWT_TYPE, APIKey
from olympia.devhub import file_validation_annotations as annotations
from olympia.files.models import File, FileUpload, FileValidation
from olympia.files.utils import (
    InvalidArchiveFile,
    InvalidManifest,
    NoManifestFound,
    SafeZip,
    UnsupportedFileType,
    parse_addon,
)


log = olympia.core.logger.getLogger('z.devhub.task')


def validate(file_, *, final_task=None, theme_specific=False):
    """Run the validator on the given File or FileUpload object. If a task has
    already begun for this file, instead return an AsyncResult object for that
    task.

    file_ can be either a File or FileUpload; if File then listed must be None;
    if FileUpload listed must be specified.

    final_task can be either None or a task that gets called after all the
    validation tasks.
    """

    # Import loop.
    from .utils import Validator

    validator = Validator(file_, theme_specific=theme_specific, final_task=final_task)
    task = validator.get_task()
    return task.delay()


def validate_and_submit(*, addon, upload, client_info, theme_specific=False):
    return validate(
        upload,
        theme_specific=theme_specific,
        final_task=submit_file.si(
            addon_pk=addon.pk, upload_pk=upload.pk, client_info=client_info
        ),
    )


@task
@use_primary_db
def submit_file(*, addon_pk, upload_pk, client_info):
    from olympia.devhub.utils import create_version_for_upload

    addon = Addon.unfiltered.get(pk=addon_pk)
    upload = FileUpload.objects.get(pk=upload_pk)
    if upload.passed_all_validations:
        create_version_for_upload(
            addon=addon, upload=upload, channel=upload.channel, client_info=client_info
        )
    else:
        log.info(
            'Skipping version creation for {upload_uuid} that failed validation'.format(
                upload_uuid=upload.uuid
            )
        )


@task
def create_initial_validation_results():
    """Returns the initial validation results for the next tasks in the
    validation chain. Should only be called directly by Validator."""
    results = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
    return results


def validation_task(fn):
    """Wrap a validation task so that it runs with the correct flags and
    handles errors (mainly because Celery's error handling does not work for
    us).

    ALL the validation tasks but `create_initial_validation_results()` should
    use this decorator. Tasks decorated with `@validation_task` should have the
    following declaration:

        @validation_task
        def my_task(results, pk):
            # ...
            return results

    Notes:

    * `results` is automagically passed to each task in the validation chain
      and created by `create_initial_validation_results()` at the beginning of
      the chain. It MUST be the first argument of the task.
    * `pk` is passed to each task when added to the validation chain.
    * the validation chain is defined in the `Validator` class.
    """

    @task(
        bind=True,
        ignore_result=False,  # We want to pass the results down.
        soft_time_limit=settings.VALIDATOR_TIMEOUT,
    )
    @use_primary_db
    @wraps(fn)
    def wrapper(task, results, pk, *args, **kwargs):
        # This is necessary to prevent timeout exceptions from being set as our
        # result, and replacing the partial validation results we'd prefer to
        # return.
        task.ignore_result = True
        try:
            # All validation tasks should receive `results`.
            if not results:
                raise Exception(
                    'Unexpected call to a validation task without `results`'
                )

            if results['errors'] > 0:
                return results

            return fn(results, pk, *args, **kwargs)
        except UnsupportedFileType as exc:
            results = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
            annotations.insert_validation_message(
                results,
                type_='error',
                message=exc.message,
                msg_id='unsupported_filetype',
            )
            return results
        except InvalidArchiveFile as exc:
            results = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
            annotations.insert_validation_message(
                results,
                type_='error',
                message=exc.message,
                msg_id='invalid_zip_file',
            )
            return results
        except BadZipFile:
            # If we raised a BadZipFile we can return a single exception with
            # a generic message indicating the zip is invalid or corrupt.
            results = deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT)
            results['messages'][0]['message'] = gettext(
                'Invalid or corrupt add-on file.'
            )
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
def validate_upload(results, upload_pk):
    """Validate a FileUpload instance.

    Should only be called directly by Validator."""
    upload = FileUpload.objects.get(pk=upload_pk)
    data = validate_file_path(upload.file_path, upload.channel)
    return {**results, **json.loads(force_str(data))}


@validation_task
def validate_file(results, file_pk):
    """Validate a File instance. If cached validation results exist, return
    those, otherwise run the validator.

    Should only be called directly by Validator."""
    file = File.objects.get(pk=file_pk)
    if file.has_been_validated:
        data = file.validation.validation
    else:
        data = validate_file_path(file.file.path, file.version.channel)
    return {**results, **json.loads(force_str(data))}


def validate_file_path(path, channel):
    """Run the validator against a file at the given path, and return the
    results, which should be a json string.

    Should only be called directly by `validate_upload` or `validate_file`
    tasks.

    Search plugins don't call the linter but get linted by
    `annotate_search_plugin_validation`.

    All legacy extensions (including dictionaries, themes etc) are unsupported.
    """
    if path.endswith('.xml'):
        # search plugins are validated directly by addons-server
        # so that we don't have to call the linter or validator
        results = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
        annotations.annotate_search_plugin_restriction(
            results=results, file_path=path, channel=channel
        )
        return json.dumps(results)

    parsed_data = {}
    try:
        parsed_data = parse_addon(path, minimal=True)
    except NoManifestFound:
        # If no manifest is found the linter will pick it up and
        # will know what message to return to the developer.
        pass
    except InvalidManifest:
        # Similarly, if we can't parse the manifest, let the linter pick that
        # up.
        pass

    log.info('Running linter on %s', path)
    results = run_addons_linter(path, channel=channel)
    annotations.annotate_validation_results(results=results, parsed_data=parsed_data)
    return json.dumps(results)


@validation_task
def forward_linter_results(results, upload_pk):
    """This task is used in the group of the validation chain to pass the
    linter results to `handle_upload_validation_result()` (the callback of the
    group).
    """
    log.debug('Called forward_linter_results() for upload_pk = %d', upload_pk)
    return results


@task
@use_primary_db
def handle_upload_validation_result(results, upload_pk, is_mozilla_signed):
    """Save a set of validation results to a FileUpload instance corresponding
    to the given upload_pk."""
    # The first task registered in the group is `forward_linter_results()`,
    # and that's what we save in the upload validation.
    #
    # Depending on what scanners were enabled, results could be a list or a
    # single item because Celery unrolls groups with a single task, see:
    # https://docs.celeryq.dev/en/v5.5.3/userguide/canvas.html#group-unrolling
    if isinstance(results, list):
        results = results[0]
    upload = FileUpload.objects.get(pk=upload_pk)
    upload.validation = json.dumps(results)
    upload.save()  # We want to hit the custom save().

    # Track the time it took from first upload through validation
    # until the results were processed and saved.
    upload_start = utc_millesecs_from_epoch(upload.created)
    now = datetime.datetime.now()
    now_ts = utc_millesecs_from_epoch(now)
    delta = now_ts - upload_start
    statsd.timing('devhub.validation_results_processed', delta)

    if not storage.exists(upload.file_path):
        # TODO: actually fix this so we can get stats. It seems that
        # the file maybe gets moved but it needs more investigation.
        log.warning(
            'Scaled upload stats were not tracked. File is missing: {}'.format(
                upload.file_path
            )
        )
        return

    size = Decimal(storage.size(upload.file_path))
    megabyte = Decimal(1024 * 1024)

    # Stash separate metrics for small / large files.
    quantifier = 'over' if size > megabyte else 'under'
    statsd.timing(f'devhub.validation_results_processed_{quantifier}_1mb', delta)

    # Scale the upload / processing time by package size (in MB)
    # so we can normalize large XPIs which naturally take longer to validate.
    scaled_delta = None
    size_in_mb = size / megabyte
    if size > 0:
        # If the package is smaller than 1MB, don't scale it. This should
        # help account for validator setup time.
        unit = size_in_mb if size > megabyte else Decimal(1)
        scaled_delta = Decimal(delta) / unit
        statsd.timing('devhub.validation_results_processed_per_mb', scaled_delta)

    log.info(
        'Time to process and save upload validation; '
        'upload.pk={upload}; processing_time={delta}; '
        'scaled_per_mb={scaled}; upload_size_in_mb={size_in_mb}; '
        'created={created}; now={now}'.format(
            delta=delta,
            upload=upload.pk,
            created=upload.created,
            now=now,
            scaled=scaled_delta,
            size_in_mb=size_in_mb,
        )
    )


# We need to explicitly not ignore the result, for the sake of `views.py` code
# that needs to wait on a result, rather than just trigger the task to save
# the result to a FileValidation object.
@task(ignore_result=False)
@use_primary_db
def handle_file_validation_result(results, file_id, *args):
    """Save a set of validation results to a FileValidation instance
    corresponding to the given file_id."""

    file_ = File.objects.get(pk=file_id)
    return FileValidation.from_json(file_, results).pk


@validation_task
def check_for_api_keys_in_file(results, upload_pk):
    upload = FileUpload.objects.get(pk=upload_pk)

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

    try:
        if len(keys) > 0:
            zipfile = SafeZip(source=upload.file_path)
            for zipinfo in zipfile.info_list:
                if zipinfo.file_size >= 64:
                    file_ = zipfile.read(zipinfo)
                    for key in keys:
                        if key.secret in file_.decode(errors='ignore'):
                            log.info(
                                'Developer API key for user %s found in '
                                'submission.' % key.user
                            )
                            if key.user == upload.user:
                                msg = gettext(
                                    'Your developer API key was '
                                    'found in the submitted file. '
                                    'To protect your account, the '
                                    'key will be revoked.'
                                )
                            else:
                                msg = gettext(
                                    'The developer API key of a '
                                    'coauthor was found in the '
                                    'submitted file. To protect '
                                    'your add-on, the key will be '
                                    'revoked.'
                                )
                            annotations.insert_validation_message(
                                results,
                                type_='error',
                                message=msg,
                                msg_id='api_key_detected',
                                compatibility_type=None,
                            )

                            # Revoke after 2 minutes to allow the developer to
                            # fetch the validation results
                            revoke_api_key.apply_async(
                                kwargs={'key_id': key.id}, countdown=120
                            )
            zipfile.close()
    except (ValidationError, BadZipFile, OSError):
        pass

    return results


@validation_task
def check_data_collection_permissions(results, upload_pk):
    upload = FileUpload.objects.get(pk=upload_pk)

    if (
        waffle.switch_is_active('enforce-data-collection-for-new-addons')
        and not upload.addon
    ):
        # When the switch is enabled and we do not have an add-on for this file
        # upload (which means it's a new add-on), we change the level of the
        # MISSING_DATA_COLLECTION_PERMISSIONS message to an error if it exists
        # in the list of messages returned by the linter.
        def update_missing_data_collection_permissions(message):
            if 'MISSING_DATA_COLLECTION_PERMISSIONS' in message.get('id', []):
                message['type'] = 'error'
                # Update the counts as well.
                results['errors'] += 1
                results['warnings'] -= 1
            return message

        results['messages'] = list(
            map(
                update_missing_data_collection_permissions,
                results.get('messages', []),
            )
        )

    return results


@task
@use_primary_db
def revoke_api_key(key_id):
    try:
        # Fetch the original key, do not use `get_jwt_key`
        # so we get access to a user object for logging later.
        original_key = APIKey.objects.get(type=SYMMETRIC_JWT_TYPE, id=key_id)
        # Fetch the current key to compare to the original,
        # throws if the key has been revoked, which also means
        # `original_key` is not active.
        current_key = APIKey.get_jwt_key(user_id=original_key.user.id)
        if current_key.key != original_key.key:
            log.info(
                'User %s has already regenerated the key, nothing to be '
                'done.' % original_key.user
            )
        else:
            with transaction.atomic():
                log.info('Revoking key for user %s.' % current_key.user)
                current_key.update(is_active=None)
                send_api_key_revocation_email(emails=[current_key.user.email])
    except APIKey.DoesNotExist:
        log.info(
            'User %s has already revoked the key, nothing to be done.'
            % original_key.user
        )
        pass


def run_addons_linter(path, channel):
    from .utils import fix_addons_linter_output

    args = [settings.ADDONS_LINTER_BIN, path, '--boring', '--output=json']

    if channel == amo.CHANNEL_UNLISTED:
        args.append('--self-hosted')

    if waffle.switch_is_active('disable-linter-xpi-autoclose'):
        args.append('--disable-xpi-autoclose')

    if waffle.switch_is_active('enable-mv3-submissions'):
        args.append('--max-manifest-version=3')
    else:
        args.append('--max-manifest-version=2')

    if settings.ADDONS_LINTER_ENABLE_SERVICE_WORKER:
        args.append('--enable-background-service-worker')

    if waffle.switch_is_active('enable-data-collection-permissions'):
        args.append('--enable-data-collection-permissions=true')
    else:
        args.append('--enable-data-collection-permissions=false')

    if not os.path.exists(path):
        raise ValueError(f'Path "{path}" is not a file or directory or does not exist.')

    stdout, stderr = (tempfile.TemporaryFile(), tempfile.TemporaryFile())

    with statsd.timer('devhub.linter'):
        process = subprocess.Popen(
            args,
            stdout=stdout,
            stderr=stderr,
            # default but explicitly set to make sure we don't open a shell.
            shell=False,
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

    parsed_data = json.loads(force_str(output))

    results = fix_addons_linter_output(parsed_data, channel)
    track_validation_stats(results)

    return results


def track_validation_stats(results):
    """
    Given a dict of validator results, log some stats.
    """
    result_kind = 'success' if results['errors'] == 0 else 'failure'
    statsd.incr(f'devhub.linter.results.all.{result_kind}')

    listed_tag = 'listed' if results['metadata']['listed'] else 'unlisted'

    # Track listed/unlisted success/fail.
    statsd.incr(f'devhub.linter.results.{listed_tag}.{result_kind}')


def _recreate_images_for_preview(preview):
    log.info('Resizing preview: %s' % preview.id)
    try:
        preview.sizes = {
            'thumbnail_format': amo.ADDON_PREVIEW_SIZES['thumbnail_format']
        }
        if storage.exists(preview.original_path):
            # We have an original size image, so we can resize that.
            src = preview.original_path
            preview.sizes['image'], preview.sizes['original'] = resize_image(
                src,
                preview.image_path,
                amo.ADDON_PREVIEW_SIZES['full'],
            )
            preview.sizes['thumbnail'], _ = resize_image(
                src,
                preview.thumbnail_path,
                amo.ADDON_PREVIEW_SIZES['thumbnail'],
                format=amo.ADDON_PREVIEW_SIZES['thumbnail_format'],
            )
        else:
            # Otherwise we can't create a new sized full image, but can
            # use it for a new thumbnail
            src = preview.image_path
            preview.sizes['thumbnail'], preview.sizes['image'] = resize_image(
                src,
                preview.thumbnail_path,
                amo.ADDON_PREVIEW_SIZES['thumbnail'],
                format=amo.ADDON_PREVIEW_SIZES['thumbnail_format'],
            )
        preview.save()
        return True
    except Exception as e:
        log.exception('Error saving preview: %s' % e)


@task
@use_primary_db
def recreate_previews(addon_ids, **kw):
    log.info(
        '[%s@%s] Getting preview sizes for addons starting at id: %s...'
        % (len(addon_ids), recreate_previews.rate_limit, addon_ids[0])
    )
    addons = Addon.objects.filter(pk__in=addon_ids).no_transforms()

    for addon in addons:
        log.info('Recreating previews for addon: %s' % addon.id)
        previews = addon.previews.all()
        for preview in previews:
            _recreate_images_for_preview(preview)


@task
@use_primary_db
def get_preview_sizes(ids, **kw):
    log.info(
        '[%s@%s] Getting preview sizes for addons starting at id: %s...'
        % (len(ids), get_preview_sizes.rate_limit, ids[0])
    )
    addons = Addon.objects.filter(pk__in=ids).no_transforms()

    for addon in addons:
        previews = addon.previews.all()
        log.info(f'Found {previews.count()} previews for: {addon.pk}')
        for preview in previews:
            try:
                log.info('Getting size for preview: %s' % preview.pk)
                sizes = {
                    'thumbnail': image_size(preview.thumbnail_path),
                    'image': image_size(preview.image_path),
                }
                preview.update(sizes=sizes)
            except Exception as err:
                log.error(f'Failed to find size of preview: {addon.pk}, error: {err}')


def failed_validation(*messages):
    """Return a validation object that looks like the add-on validator."""
    m = []
    for msg in messages:
        m.append({'type': 'error', 'message': msg, 'tier': 1})

    return json.dumps({'errors': 1, 'success': False, 'messages': m})


def check_content_type(response, content_type, no_ct_message, wrong_ct_message):
    if not response.headers.get('Content-Type', '').startswith(content_type):
        if 'Content-Type' in response.headers:
            raise Exception(
                wrong_ct_message % (content_type, response.headers['Content-Type'])
            )
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
@use_primary_db
def send_initial_submission_acknowledgement_email(addon_pk, channel, email, **kw):
    log.info(
        '[1@None] Sending initial_submission acknowledgement email for %s to %s',
        addon_pk,
        email,
    )
    try:
        addon = Addon.objects.get(pk=addon_pk)
    except Addon.DoesNotExist:
        # Add-on already deleted ? Ignore.
        return
    with override_url_prefix(locale=addon.default_locale):
        context = {
            'addon_name': str(addon.name),
            'app': str(amo.FIREFOX.pretty),
            'listed': channel == amo.CHANNEL_LISTED,
            'detail_url': addon.get_absolute_url(),
        }
        subject = (
            f'Mozilla Add-ons: {addon.name} has been submitted to addons.mozilla.org!'
        )
        html_template = 'devhub/emails/submission.html'
        text_template = 'devhub/emails/submission.txt'
        return send_html_mail_jinja(
            subject,
            html_template,
            text_template,
            context,
            recipient_list=[email],
            use_deny_list=False,
            perm_setting='individual_contact',
        )


def send_api_key_revocation_email(emails):
    log.info('[1@None] Sending API key revocation email to %s.' % emails)
    subject = gettext(
        'Mozilla Security Notice: Your AMO API credentials have been revoked'
    )
    template = loader.get_template('devhub/emails/submission_api_key_revocation.txt')
    context = {'api_keys_url': reverse('devhub.api_key')}
    send_mail(
        subject,
        template.render(context),
        recipient_list=emails,
        use_deny_list=False,
        perm_setting='individual_contact',
    )
