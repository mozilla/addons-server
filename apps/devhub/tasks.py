# -*- coding: utf-8 -*-
import json
import logging
import os
import socket
import sys
import tempfile
import traceback
import urllib2

from django.conf import settings
from django.core.files.storage import default_storage as storage

from cache_nuggets.lib import memoize
from celeryutils import task
from django_statsd.clients import statsd
from tower import ugettext as _

import amo
from amo.decorators import write, set_modified_on
from amo.utils import resize_image, send_html_mail_jinja
from addons.models import Addon
from applications.models import AppVersion
from devhub import perf
from files.helpers import copyfileobj
from files.models import FileUpload, File, FileValidation
from zadmin.models import get_config

from PIL import Image


log = logging.getLogger('z.devhub.task')


@task
@write
def validator(upload_id, **kw):
    if not settings.VALIDATE_ADDONS:
        return None
    log.info('VALIDATING: %s' % upload_id)
    upload = FileUpload.objects.using('default').get(pk=upload_id)
    try:
        result = run_validator(upload.path)
        upload.validation = result
        upload.save()  # We want to hit the custom save().
    except:
        # Store the error with the FileUpload job, then raise
        # it for normal logging.
        tb = traceback.format_exception(*sys.exc_info())
        upload.update(task_error=''.join(tb))
        raise


@task
@write
def compatibility_check(upload_id, app_guid, appversion_str, **kw):
    if not settings.VALIDATE_ADDONS:
        return None
    log.info('COMPAT CHECK for upload %s / app %s version %s'
             % (upload_id, app_guid, appversion_str))
    upload = FileUpload.objects.get(pk=upload_id)
    app = amo.APP_GUIDS.get(app_guid)
    appver = AppVersion.objects.get(application=app.id, version=appversion_str)
    try:
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
    except:
        # Store the error with the FileUpload job, then raise
        # it for normal logging.
        tb = traceback.format_exception(*sys.exc_info())
        upload.update(task_error=''.join(tb))
        raise


@task
@write
def file_validator(file_id, **kw):
    if not settings.VALIDATE_ADDONS:
        return None
    log.info('VALIDATING file: %s' % file_id)
    file = File.objects.get(pk=file_id)
    result = run_validator(file.file_path)
    return FileValidation.from_json(file, result)


@memoize('validator-apps', 60 * 60)
def get_apps():
    apps = {}
    for id, app in amo.APP_IDS.iteritems():
        apps[id] = dict(guid=app.guid, versions=[],
                        name=amo.APPS_ALL[id].short)

    versions = (AppVersion.objects.values_list('application', 'version')
                .order_by('version_int'))
    for app, version in versions:
        try:
            apps[app]['versions'].append(version)
        except KeyError:
            # Sunbird is still in the database but shouldn't show up here.
            pass

    return apps


@memoize('validator-libraries', 60 * 60)
def get_libraries():
    data = get_config('validator-known-libraries')

    if data is None:
        # This should generally only happen in tests.
        import validator
        path = os.path.join(validator.__path__[0], 'libraries.json')
        data = open(path, 'r').read()

    return json.loads(data)


def run_validator(file_path, for_appversions=None, test_all_tiers=False,
                  overrides=None, compat=False):
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

    To validate the addon for compatibility with Firefox 5 and 6,
    you'd pass in::

        for_appversions={amo.FIREFOX.guid: ['5.0.*', '6.0.*']}

    Not all application versions will have a set of registered
    compatibility tests.
    """

    from validator.validate import validate

    path = file_path
    if path and not os.path.exists(path) and storage.exists(path):
        path = tempfile.mktemp(suffix='_' + os.path.basename(file_path))
        with open(path, 'wb') as f:
            copyfileobj(storage.open(file_path), f)
        temp = True
    else:
        temp = False
    try:
        with statsd.timer('devhub.validator'):
            return validate(path,
                            for_appversions=for_appversions,
                            format='json',
                            # When False, this flag says to stop testing after
                            # one tier fails.
                            determined=test_all_tiers,
                            approved_applications=get_apps(),
                            library_metadata=get_libraries(),
                            spidermonkey=settings.SPIDERMONKEY,
                            overrides=overrides,
                            timeout=settings.VALIDATOR_TIMEOUT,
                            compat_test=compat)
    finally:
        if temp:
            os.remove(path)


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
