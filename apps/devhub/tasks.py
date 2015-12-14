# -*- coding: utf-8 -*-
import json
import logging
import os
import socket
import urllib2
from copy import deepcopy
from functools import wraps
from tempfile import NamedTemporaryFile

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django.core.management import call_command

from celery.exceptions import SoftTimeLimitExceeded
from celery.result import AsyncResult
from django_statsd.clients import statsd
from tower import ugettext as _

import amo
import validator
from amo.celery import task
from amo.decorators import atomic, set_modified_on, write
from amo.utils import resize_image, send_html_mail_jinja
from addons.models import Addon
from applications.management.commands import dump_apps
from applications.models import AppVersion
from devhub import perf
from files.helpers import copyfileobj
from files.models import FileUpload, File, FileValidation
from versions.models import Version

from PIL import Image


log = logging.getLogger('z.devhub.task')


def validate(file_, listed=None, subtask=None):
    """Run the validator on the given File or FileUpload object, and annotate
    the results using the ValidationAnnotator. If a task has already begun
    for this file, instead return an AsyncResult object for that task."""

    # Import loop.
    from .utils import ValidationAnnotator
    annotator = ValidationAnnotator(file_, listed=listed)

    task_id = cache.get(annotator.cache_key)
    if task_id:
        return AsyncResult(task_id)
    else:
        chain = annotator.task
        if subtask is not None:
            chain |= subtask
        result = chain.delay()
        cache.set(annotator.cache_key, result.task_id, 5 * 60)
        return result


def validate_and_submit(addon, file_, listed=None):
    return validate(file_, listed=listed,
                    subtask=submit_file.si(addon.pk, file_.pk))


@task
@write
def submit_file(addon_pk, file_pk):
    addon = Addon.unfiltered.get(pk=addon_pk)
    file_ = FileUpload.objects.get(pk=file_pk)
    if file_.passed_all_validations:
        create_version_for_upload(addon, file_)
    else:
        log.info('Skipping version creation for {file_id} that failed '
                 'validation'.format(file_id=file_pk))


@atomic
def create_version_for_upload(addon, file_):
    if (addon.fileupload_set.filter(created__gt=file_.created,
                                    version=file_.version).exists()
            or addon.versions.filter(version=file_.version).exists()):
        log.info('Skipping Version creation for {file_id} that would cause '
                 'duplicate version'.format(file_id=file_.pk))
    else:
        # Import loop.
        from devhub.views import auto_sign_version

        log.info('Creating version for {file_id} that passed '
                 'validation'.format(file_id=file_.pk))
        version = Version.from_upload(file_, addon, [amo.PLATFORM_ALL.id])
        # The add-on's status will be STATUS_NULL when its first version is
        # created because the version has no files when it gets added and it
        # gets flagged as invalid. We need to manually set the status.
        # TODO: Handle sideload add-ons. This assumes the user wants a prelim
        # review since listed and sideload aren't supported for creation yet.
        if addon.status == amo.STATUS_NULL:
            addon.update(status=amo.STATUS_LITE)
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

            if hash_:
                # Import loop.
                from .utils import ValidationComparator
                ValidationComparator(result).annotate_results(hash_)

            return result
        except Exception, e:
            log.exception('Unhandled error during validation: %r' % e)
            return deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION)
        finally:
            # But we do want to return a result after that exception has
            # been handled.
            task.ignore_result = False
    return wrapper


@validation_task
def validate_file_path(path, hash_, listed, **kw):
    """Run the validator against a file at the given path, and return the
    results.

    Should only be called directly by ValidationAnnotator."""

    return run_validator(path, listed=listed)


@validation_task
def validate_file(file_id, hash_, **kw):
    """Validate a File instance. If cached validation results exist, return
    those, otherwise run the validator.

    Should only be called directly by ValidationAnnotator."""

    file_ = File.objects.get(pk=file_id)
    try:
        return file_.validation.validation
    except FileValidation.DoesNotExist:
        return run_validator(file_.current_file_path,
                             listed=file_.version.addon.is_listed)


@task
@write
def handle_upload_validation_result(results, upload_id, annotate=True):
    """Annotates a set of validation results, unless `annotate` is false, and
    saves them to the given FileUpload instance."""
    if annotate:
        results = annotate_validation_results(results)

    upload = FileUpload.objects.get(pk=upload_id)
    upload.validation = json.dumps(results)
    upload.save()  # We want to hit the custom save().


# We need to explicitly not ignore the result, for the sake of `views.py` code
# that needs to wait on a result, rather than just trigger the task to save
# the result to a FileValidation object.
@task(ignore_result=False)
@write
def handle_file_validation_result(results, file_id, annotate=True):
    """Annotates a set of validation results, unless `annotate is false, and
    saves them to the given File instance."""
    if annotate:
        results = annotate_validation_results(results)

    file_ = File.objects.get(pk=file_id)
    return FileValidation.from_json(file_, results)


def addon_can_be_signed(validation):
    """
    Given a dict of add-on validation results, returns True if add-on can be
    signed.
    """
    summary = validation.get('signing_summary', {})
    # Check for any errors that should prevent signing.
    return (summary.get('low', 0) == 0 and
            summary.get('medium', 0) == 0 and
            summary.get('high', 0) == 0)


def annotate_validation_results(results):
    """Annotates validation results with information such as whether the
    results pass auto validation, and which results are unchanged from a
    previous submission and can be ignored."""

    if isinstance(results, dict):
        validation = results
    else:
        # Import loop.
        from .utils import ValidationComparator

        validation = (ValidationComparator(results[1])
                      .compare_results(results[0]))

    validation.setdefault('signing_summary',
                          {'trivial': 0, 'low': 0,
                           'medium': 0, 'high': 0})

    validation['passed_auto_validation'] = addon_can_be_signed(validation)

    if not settings.SIGNING_SERVER:
        validation = skip_signing_warning(validation)

    return validation


def skip_signing_warning(result):
    """Remove the "Package already signed" warning if we're not signing."""
    try:
        messages = result['messages']
    except (KeyError, ValueError):
        return result

    messages = [m for m in messages if 'signed_xpi' not in m['id']]
    diff = len(result['messages']) - len(messages)
    if diff:  # We did remove a warning.
        result['messages'] = messages
        result['warnings'] -= diff
    return result


@task(soft_time_limit=settings.VALIDATOR_TIMEOUT)
@write
def compatibility_check(upload_id, app_guid, appversion_str, **kw):
    log.info('COMPAT CHECK for upload %s / app %s version %s'
             % (upload_id, app_guid, appversion_str))
    upload = FileUpload.objects.get(pk=upload_id)
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
        Normally the validator gets info from install.rdf but there are a
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
    if not settings.VALIDATE_ADDONS:
        # This should only ever be set on development instances.
        # Don't run the validator, just return a skeleton passing result set.
        results = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
        results['metadata']['listed'] = listed
        return json.dumps(results)

    from validator.validate import validate

    apps = dump_apps.Command.JSON_PATH
    if not os.path.exists(apps):
        call_command('dump_apps')

    with NamedTemporaryFile(suffix='_' + os.path.basename(path)) as temp:
        if path and not os.path.exists(path) and storage.exists(path):
            # This file doesn't exist locally. Write it to our
            # currently-open temp file and switch to that path.
            copyfileobj(storage.open(path), temp.file)
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
                spidermonkey=settings.SPIDERMONKEY,
                overrides=overrides,
                compat_test=compat,
                listed=listed
            )

        track_validation_stats(json_result)

        return json_result


def track_validation_stats(json_result):
    """
    Given a raw JSON string of validator results, log some stats.
    """
    result = json.loads(json_result)
    result_kind = 'success' if result['errors'] == 0 else 'failure'
    statsd.incr('devhub.validator.results.all.{}'.format(result_kind))

    listed_tag = 'listed' if result['metadata']['listed'] else 'unlisted'
    signable_tag = ('is_signable' if addon_can_be_signed(result)
                    else 'is_not_signable')

    # Track listed/unlisted success/fail.
    statsd.incr('devhub.validator.results.{}.{}'
                .format(listed_tag, result_kind))
    # Track how many listed/unlisted add-ons can be automatically signed.
    statsd.incr('devhub.validator.results.{}.{}'
                .format(listed_tag, signable_tag))


@task(rate_limit='4/m')
@write
def flag_binary(ids, **kw):
    log.info('[%s@%s] Flagging binary addons starting with id: %s...'
             % (len(ids), flag_binary.rate_limit, ids[0]))
    addons = Addon.objects.filter(pk__in=ids).no_transforms()

    latest = kw.pop('latest', True)

    for addon in addons:
        try:
            log.info('Validating addon with id: %s' % addon.pk)
            files = (File.objects.filter(version__addon=addon)
                                 .exclude(status=amo.STATUS_DISABLED)
                                 .order_by('-created'))
            if latest:
                files = [files[0]]
            for file in files:
                result = json.loads(run_validator(file.file_path))
                metadata = result['metadata']
                binary = (metadata.get('contains_binary_extension', False) or
                          metadata.get('contains_binary_content', False))
                binary_components = metadata.get('binary_components', False)
                log.info('Updating binary flags for addon with id=%s: '
                         'binary -> %s, binary_components -> %s' % (
                             addon.pk, binary, binary_components))
                file.update(binary=binary, binary_components=binary_components)
        except Exception, err:
            log.error('Failed to run validation on addon id: %s, %s'
                      % (addon.pk, err))


@task
@set_modified_on
def resize_icon(src, dst, size, locally=False, **kw):
    """Resizes addon icons."""
    log.info('[1@None] Resizing icon: %s' % dst)
    try:
        if isinstance(size, list):
            for s in size:
                resize_image(src, '%s-%s.png' % (dst, s), (s, s),
                             remove_src=False, locally=locally)
            if locally:
                os.remove(src)
            else:
                storage.delete(src)
        else:
            resize_image(src, dst, (size, size), remove_src=True,
                         locally=locally)
        return True
    except Exception, e:
        log.error("Error saving addon icon: %s" % e)


@task
@set_modified_on
def resize_preview(src, instance, **kw):
    """Resizes preview images and stores the sizes on the preview."""
    thumb_dst, full_dst = instance.thumbnail_path, instance.image_path
    sizes = {}
    log.info('[1@None] Resizing preview and storing size: %s' % thumb_dst)
    try:
        sizes['thumbnail'] = resize_image(src, thumb_dst,
                                          amo.ADDON_PREVIEW_SIZES[0],
                                          remove_src=False)
        sizes['image'] = resize_image(src, full_dst,
                                      amo.ADDON_PREVIEW_SIZES[1],
                                      remove_src=False)
        instance.sizes = sizes
        instance.save()
        return True
    except Exception, e:
        log.error("Error saving preview: %s" % e)
    finally:
        # Finally delete the temporary now useless source file.
        if os.path.exists(src):
            os.unlink(src)


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
                    'thumbnail': Image.open(
                        storage.open(preview.thumbnail_path)).size,
                    'image': Image.open(storage.open(preview.image_path)).size,
                }
                preview.update(sizes=sizes)
            except Exception, err:
                log.error('Failed to find size of preview: %s, error: %s'
                          % (addon.pk, err))


@task
@write
def convert_purified(ids, **kw):
    log.info('[%s@%s] Converting fields to purified starting at id: %s...'
             % (len(ids), convert_purified.rate_limit, ids[0]))
    fields = ['the_reason', 'the_future']
    for addon in Addon.objects.filter(pk__in=ids):
        flag = False
        for field in fields:
            value = getattr(addon, field)
            if value:
                value.clean()
                if (value.localized_string_clean != value.localized_string):
                    flag = True
        if flag:
            log.info('Saving addon: %s to purify fields' % addon.pk)
            addon.save()


def failed_validation(*messages):
    """Return a validation object that looks like the add-on validator."""
    m = []
    for msg in messages:
        m.append({'type': 'error', 'message': msg, 'tier': 1})

    return json.dumps({'errors': 1, 'success': False, 'messages': m})


def _fetch_content(url):
    try:
        return urllib2.urlopen(url, timeout=15)
    except urllib2.HTTPError, e:
        raise Exception(_('%s responded with %s (%s).') % (url, e.code, e.msg))
    except urllib2.URLError, e:
        # Unpack the URLError to try and find a useful message.
        if isinstance(e.reason, socket.timeout):
            raise Exception(_('Connection to "%s" timed out.') % url)
        elif isinstance(e.reason, socket.gaierror):
            raise Exception(_('Could not contact host at "%s".') % url)
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
def start_perf_test_for_file(file_id, os_name, app_name, **kw):
    log.info('[@%s] Starting perf tests for file %s on %s / %s'
             % (start_perf_test_for_file.rate_limit, file_id,
                os_name, app_name))
    file_ = File.objects.get(pk=file_id)
    # TODO(Kumar) store token to retrieve results later?
    perf.start_perf_test(file_, os_name, app_name)


@task
def send_welcome_email(addon_pk, emails, context, **kw):
    log.info(u'[1@None] Sending welcome email for %s to %s.' %
             (addon_pk, emails))
    app = context.get('app', unicode(amo.FIREFOX.pretty))
    subject = u'Mozilla Add-ons: Thanks for submitting a %s Add-on!' % app
    html_template = 'devhub/email/submission.html'
    text_template = 'devhub/email/submission.txt'
    return send_html_mail_jinja(subject, html_template, text_template,
                                context, recipient_list=emails,
                                from_email=settings.NOBODY_EMAIL,
                                use_blacklist=False,
                                perm_setting='individual_contact',
                                headers={'Reply-To': settings.EDITORS_EMAIL})
