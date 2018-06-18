# -*- coding: utf-8 -*-
import datetime
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import urllib2
import shutil

from copy import deepcopy
from decimal import Decimal
from functools import wraps
from tempfile import NamedTemporaryFile
from zipfile import BadZipfile

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django.core.management import call_command
from django.core.validators import ValidationError
from django.db import transaction
from django.template import loader
from django.utils.translation import ugettext

import validator
import waffle

from celery.exceptions import SoftTimeLimitExceeded
from celery.result import AsyncResult
from django_statsd.clients import statsd

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon, Persona, Preview
from olympia.amo.celery import task
from olympia.amo.decorators import atomic, set_modified_on, write
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import (
    image_size, pngcrush_image, resize_image, send_html_mail_jinja, send_mail,
    utc_millesecs_from_epoch)
from olympia.api.models import SYMMETRIC_JWT_TYPE, APIKey
from olympia.applications.management.commands import dump_apps
from olympia.applications.models import AppVersion
from olympia.files.models import File, FileUpload, FileValidation
from olympia.files.utils import parse_addon, SafeZip
from olympia.versions.compare import version_int
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.devhub.task')


def validate(file_, listed=None, subtask=None, synchronous=False):
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
        chain = validator.task
        if subtask is not None:
            chain |= subtask

        if synchronous:
            result = chain.apply()
        else:
            result = chain.delay()
            cache.set(validator.cache_key, result.task_id, 5 * 60)

        return result


def validate_and_submit(addon, file_, channel):
    return validate(
        file_, listed=(channel == amo.RELEASE_CHANNEL_LISTED),
        subtask=submit_file.si(addon.pk, file_.pk, channel))


@task
@write
def submit_file(addon_pk, upload_pk, channel):
    addon = Addon.unfiltered.get(pk=addon_pk)
    upload = FileUpload.objects.get(pk=upload_pk)
    if upload.passed_all_validations:
        create_version_for_upload(addon, upload, channel)
    else:
        log.info('Skipping version creation for {upload_uuid} that failed '
                 'validation'.format(upload_uuid=upload.uuid))


@atomic
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
        from olympia.devhub.views import auto_sign_version

        log.info('Creating version for {upload_uuid} that passed '
                 'validation'.format(upload_uuid=upload.uuid))
        # Note: if we somehow managed to get here with an invalid add-on,
        # parse_addon() will raise ValidationError and the task will fail
        # loudly in sentry.
        parsed_data = parse_addon(upload, addon, user=upload.user)
        version = Version.from_upload(
            upload, addon, [amo.PLATFORM_ALL.id], channel,
            parsed_data=parsed_data)
        # The add-on's status will be STATUS_NULL when its first version is
        # created because the version has no files when it gets added and it
        # gets flagged as invalid. We need to manually set the status.
        if (addon.status == amo.STATUS_NULL and
                channel == amo.RELEASE_CHANNEL_LISTED):
            addon.update(status=amo.STATUS_NOMINATED)
        auto_sign_version(version)


# Override the validator's stock timeout exception so that it can
# detect and report celery timeouts.
validator.ValidationTimeout = SoftTimeLimitExceeded


def validation_task(fn):
    """Wrap a validation task so that it runs with the correct flags, then
    parse and annotate the results before returning."""

    @task(bind=True, ignore_result=False,  # Required for groups/chains.
          soft_time_limit=settings.VALIDATOR_TIMEOUT)
    @wraps(fn)
    def wrapper(task, id_, hash_, *args, **kw):
        # This is necessary to prevent timeout exceptions from being set
        # as our result, and replacing the partial validation results we'd
        # prefer to return.
        task.ignore_result = True
        try:
            data = fn(id_, hash_, *args, **kw)
            result = json.loads(data)
            return result
        except Exception as e:
            log.exception('Unhandled error during validation: %r' % e)

            is_webextension = kw.get('is_webextension', False)
            if is_webextension:
                return deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT)
            return deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION)
        finally:
            # But we do want to return a result after that exception has
            # been handled.
            task.ignore_result = False
    return wrapper


@validation_task
def validate_file_path(path, hash_, listed=True, is_webextension=False, **kw):
    """Run the validator against a file at the given path, and return the
    results.

    Should only be called directly by Validator."""
    if is_webextension:
        return run_addons_linter(path, listed=listed)
    return run_validator(path, listed=listed)


@validation_task
def validate_file(file_id, hash_, is_webextension=False, **kw):
    """Validate a File instance. If cached validation results exist, return
    those, otherwise run the validator.

    Should only be called directly by Validator."""

    file_ = File.objects.get(pk=file_id)
    try:
        return file_.validation.validation
    except FileValidation.DoesNotExist:
        listed = file_.version.channel == amo.RELEASE_CHANNEL_LISTED
        if is_webextension:
            return run_addons_linter(
                file_.current_file_path, listed=listed)

        return run_validator(file_.current_file_path,
                             listed=listed)


@task
@write
def handle_upload_validation_result(
        results, upload_pk, channel, is_mozilla_signed):
    """Annotate a set of validation results and save them to the given
    FileUpload instance."""
    upload = FileUpload.objects.get(pk=upload_pk)
    # Restrictions applying to new legacy submissions apply if:
    # - It's the very first upload (there is no addon id yet)
    # - It's the first upload in that channel
    is_new_upload = (
        not upload.addon_id or
        not upload.addon.find_latest_version(channel=channel, exclude=()))

    # Annotate results with potential legacy add-ons restrictions.
    if not is_mozilla_signed:
        results = annotate_legacy_addon_restrictions(
            results=results, is_new_upload=is_new_upload)

    # Check for API keys in submissions.
    # Make sure it is extension-like, e.g. no LWT or search plugin
    try:
        results = check_for_api_keys_in_file(results=results, upload=upload)
    except (ValidationError, BadZipfile, IOError):
        pass

    # Annotate results with potential webext warnings on new versions.
    if upload.addon_id and upload.version:
        results = annotate_webext_incompatibilities(
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
@write
def handle_file_validation_result(results, file_id, *args):
    """Annotate a set of validation results and save them to the given File
    instance."""

    file_ = File.objects.get(pk=file_id)

    annotate_webext_incompatibilities(
        results=results, file_=file_, addon=file_.version.addon,
        version_string=file_.version.version, channel=file_.version.channel)

    return FileValidation.from_json(file_, results)


def insert_validation_message(results, type_='error', message='', msg_id='',
                              compatibility_type=None):
    messages = results['messages']
    messages.insert(0, {
        'tier': 1,
        'type': type_,
        'id': ['validation', 'messages', msg_id],
        'message': message,
        'description': [],
        'compatibility_type': compatibility_type,
    })
    # Need to increment 'errors' or 'warnings' count, so add an extra 's' after
    # the type_ to increment the right entry.
    results['{}s'.format(type_)] += 1


def annotate_legacy_addon_restrictions(results, is_new_upload):
    """
    Annotate validation results to restrict uploads of legacy
    (non-webextension) add-ons if specific conditions are met.
    """
    metadata = results.get('metadata', {})
    target_apps = metadata.get('applications', {})
    max_target_firefox_version = max(
        version_int(target_apps.get('firefox', {}).get('max', '')),
        version_int(target_apps.get('android', {}).get('max', ''))
    )

    is_webextension = metadata.get('is_webextension') is True
    is_extension_or_complete_theme = (
        # Note: annoyingly, `detected_type` is at the root level, not under
        # `metadata`.
        results.get('detected_type') in ('theme', 'extension'))
    is_targeting_firefoxes_only = (
        set(target_apps.keys()).intersection(('firefox', 'android')) ==
        set(target_apps.keys())
    )
    is_targeting_thunderbird_or_seamonkey_only = (
        set(target_apps.keys()).intersection(('thunderbird', 'seamonkey')) ==
        set(target_apps.keys())
    )
    is_targeting_firefox_lower_than_53_only = (
        metadata.get('strict_compatibility') is True and
        # version_int('') is actually 200100. If strict compatibility is true,
        # the validator should have complained about the non-existant max
        # version, but it doesn't hurt to check that the value is sane anyway.
        max_target_firefox_version > 200100 and
        max_target_firefox_version < 53000000000000
    )
    is_targeting_firefox_higher_or_equal_than_57 = (
        max_target_firefox_version >= 57000000000000 and
        max_target_firefox_version < 99000000000000)

    # Thunderbird/Seamonkey only add-ons are moving to addons.thunderbird.net.
    if (waffle.switch_is_active('disallow-thunderbird-and-seamonkey') and
            is_targeting_thunderbird_or_seamonkey_only):
        msg = ugettext(
            u'Add-ons for Thunderbird and SeaMonkey are now listed and '
            u'maintained on addons.thunderbird.net. You can use the same '
            u'account to update your add-ons on the new site.')

        insert_validation_message(
            results, message=msg, msg_id='thunderbird_and_seamonkey_migration')

    # New legacy add-ons targeting Firefox only must target Firefox 53 or
    # lower, strictly. Extensions targeting multiple other apps are exempt from
    # this.
    elif (is_new_upload and
            is_extension_or_complete_theme and
            not is_webextension and
            is_targeting_firefoxes_only and
            not is_targeting_firefox_lower_than_53_only):

        msg = ugettext(
            u'Starting with Firefox 53, new add-ons on this site can '
            u'only be WebExtensions.')

        insert_validation_message(
            results, message=msg, msg_id='legacy_addons_restricted')

    # All legacy add-ons (new or upgrades) targeting Firefox must target
    # Firefox 56.* or lower, even if they target multiple apps.
    elif (is_extension_or_complete_theme and
            not is_webextension and
            is_targeting_firefox_higher_or_equal_than_57):
        # Note: legacy add-ons targeting '*' (which is the default for sdk
        # add-ons) are excluded from this error, and instead are silently
        # rewritten as supporting '56.*' in the manifest parsing code.
        msg = ugettext(
            u'Legacy add-ons are not compatible with Firefox 57 or higher. '
            u'Use a maxVersion of 56.* or lower.')

        insert_validation_message(
            results, message=msg, msg_id='legacy_addons_max_version')

    return results


def annotate_webext_incompatibilities(results, file_, addon, version_string,
                                      channel):
    """Check for WebExtension upgrades or downgrades.

    We avoid developers to downgrade their webextension to a XUL add-on
    at any cost and warn in case of an upgrade from XUL add-on to a
    WebExtension.

    Firefox doesn't support a downgrade.

    See https://github.com/mozilla/addons-server/issues/3061 and
    https://github.com/mozilla/addons-server/issues/3082 for more details.
    """
    from .utils import find_previous_version

    previous_version = find_previous_version(
        addon, file_, version_string, channel)

    if not previous_version:
        return results

    is_webextension = results['metadata'].get('is_webextension', False)
    was_webextension = previous_version and previous_version.is_webextension

    if is_webextension and not was_webextension:
        results['is_upgrade_to_webextension'] = True

        msg = ugettext(
            'We allow and encourage an upgrade but you cannot reverse '
            'this process. Once your users have the WebExtension '
            'installed, they will not be able to install a legacy add-on.')

        messages = results['messages']
        messages.insert(0, {
            'tier': 1,
            'type': 'warning',
            'id': ['validation', 'messages', 'webext_upgrade'],
            'message': msg,
            'description': [],
            'compatibility_type': None})
        results['warnings'] += 1
    elif was_webextension and not is_webextension:
        msg = ugettext(
            'You cannot update a WebExtensions add-on with a legacy '
            'add-on. Your users would not be able to use your new version '
            'because Firefox does not support this type of update.')

        messages = results['messages']
        messages.insert(0, {
            'tier': 1,
            'type': ('error' if channel == amo.RELEASE_CHANNEL_LISTED
                     else 'warning'),
            'id': ['validation', 'messages', 'webext_downgrade'],
            'message': msg,
            'description': [],
            'compatibility_type': None})
        if channel == amo.RELEASE_CHANNEL_LISTED:
            results['errors'] += 1
        else:
            results['warnings'] += 1

    return results


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
        zipfile.is_valid()
        for zipinfo in zipfile.info_list:
            if zipinfo.file_size >= 64:
                file_ = zipfile.read(zipinfo)
                for key in keys:
                    if key.secret in file_.decode(encoding='unicode-escape',
                                                  errors="ignore"):
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
                        insert_validation_message(
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
@write
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


@task(soft_time_limit=settings.VALIDATOR_TIMEOUT)
@write
def compatibility_check(upload_pk, app_guid, appversion_str, **kw):
    log.info('COMPAT CHECK for upload %s / app %s version %s'
             % (upload_pk, app_guid, appversion_str))
    upload = FileUpload.objects.get(pk=upload_pk)
    app = amo.APP_GUIDS.get(app_guid)
    appver = AppVersion.objects.get(application=app.id, version=appversion_str)

    result = run_validator(
        upload.path,
        for_appversions={app_guid: [appversion_str]},
        test_all_tiers=True,
        # Ensure we only check compatibility against this one specific
        # version:
        overrides={'targetapp_minVersion': {app_guid: appversion_str},
                   'targetapp_maxVersion': {app_guid: appversion_str}},
        compat=True)

    upload.validation = result
    upload.compat_with_app = app.id
    upload.compat_with_appver = appver
    upload.save()  # We want to hit the custom save().


def run_validator(path, for_appversions=None, test_all_tiers=False,
                  overrides=None, compat=False, listed=True):
    """A pre-configured wrapper around the addon validator.

    *file_path*
        Path to addon / extension file to validate.

    *for_appversions=None*
        An optional dict of application versions to validate this addon
        for. The key is an application GUID and its value is a list of
        versions.

    *test_all_tiers=False*
        When False (default) the validator will not continue if it
        encounters fatal errors.  When True, all tests in all tiers are run.
        See bug 615426 for discussion on this default.

    *overrides=None*
        Normally the validator gets info from the manifest but there are a
        few things we need to override. See validator for supported overrides.
        Example: {'targetapp_maxVersion': {'<app guid>': '<version>'}}

    *compat=False*
        Set this to `True` when performing a bulk validation. This allows the
        validator to ignore certain tests that should not be run during bulk
        validation (see bug 735841).

    *listed=True*
        If the addon is unlisted, treat it as if it was a self hosted one
        (don't fail on the presence of an updateURL).

    To validate the addon for compatibility with Firefox 5 and 6,
    you'd pass in::

        for_appversions={amo.FIREFOX.guid: ['5.0.*', '6.0.*']}

    Not all application versions will have a set of registered
    compatibility tests.
    """
    from validator.validate import validate

    apps = dump_apps.Command.get_json_path()

    if not os.path.exists(apps):
        call_command('dump_apps')

    suffix = '_' + os.path.basename(path)

    with NamedTemporaryFile(suffix=suffix, dir=settings.TMP_PATH) as temp:
        if path and not os.path.exists(path) and storage.exists(path):
            # This file doesn't exist locally. Write it to our
            # currently-open temp file and switch to that path.
            shutil.copyfileobj(storage.open(path), temp.file)
            path = temp.name

        with statsd.timer('devhub.validator'):
            json_result = validate(
                path,
                for_appversions=for_appversions,
                format='json',
                # When False, this flag says to stop testing after one
                # tier fails.
                determined=test_all_tiers,
                approved_applications=apps,
                overrides=overrides,
                compat_test=compat,
                listed=listed
            )

        track_validation_stats(json_result)

        return json_result


def run_addons_linter(path, listed=True):
    from .utils import fix_addons_linter_output

    args = [
        settings.ADDONS_LINTER_BIN,
        path,
        '--boring',
        '--output=json'
    ]

    if not listed:
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

    parsed_data = json.loads(output)

    result = json.dumps(fix_addons_linter_output(parsed_data, listed))
    track_validation_stats(result, addons_linter=True)

    return result


def track_validation_stats(json_result, addons_linter=False):
    """
    Given a raw JSON string of validator results, log some stats.
    """
    result = json.loads(json_result)
    result_kind = 'success' if result['errors'] == 0 else 'failure'
    runner = 'linter' if addons_linter else 'validator'
    statsd.incr('devhub.{}.results.all.{}'.format(runner, result_kind))

    listed_tag = 'listed' if result['metadata']['listed'] else 'unlisted'

    # Track listed/unlisted success/fail.
    statsd.incr('devhub.{}.results.{}.{}'
                .format(runner, listed_tag, result_kind))


@task
@write
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
@write
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
@write
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
        with open(source) as fd:
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
        if not preview.sizes:
            preview.sizes = {}
        if storage.exists(preview.original_path):
            # We have an original size image, so we can resize that.
            src = preview.original_path
            preview.sizes['image'], _ = resize_image(
                src, preview.image_path, amo.ADDON_PREVIEW_SIZES['full'])
        else:
            # Otherwise we can't create a new sized full image, but can
            # use it for a new thumbnail
            src = preview.image_path
        # But we should resize the thumbnail regardless.
        preview.sizes['thumbnail'], _ = resize_image(
            src, preview.thumbnail_path, amo.ADDON_PREVIEW_SIZES['thumb'])
        preview.save()
        return True
    except Exception as e:
        log.exception("Error saving preview: %s" % e)


@task
@write
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
@write
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


def _fetch_content(url):
    try:
        return urllib2.urlopen(url, timeout=15)
    except urllib2.HTTPError as e:
        raise Exception(
            ugettext('%s responded with %s (%s).') % (url, e.code, e.msg))
    except urllib2.URLError as e:
        # Unpack the URLError to try and find a useful message.
        if isinstance(e.reason, socket.timeout):
            raise Exception(ugettext('Connection to "%s" timed out.') % url)
        elif isinstance(e.reason, socket.gaierror):
            raise Exception(ugettext('Could not contact host at "%s".') % url)
        else:
            raise Exception(str(e.reason))


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
