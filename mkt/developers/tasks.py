# -*- coding: utf-8 -*-
import base64
import json
import logging
import os
import sys
import traceback
import urlparse
import uuid
import zipfile
from datetime import date

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils.http import urlencode

import requests
from appvalidator import validate_app, validate_packaged_app
from celery_tasktree import task_with_callbacks
from celeryutils import task
from django_statsd.clients import statsd
from PIL import Image
from tower import ugettext as _

import amo
from addons.models import Addon
from amo.decorators import set_modified_on, write
from amo.helpers import absolutify
from amo.utils import remove_icons, resize_image, send_mail_jinja, strip_bom
from files.models import FileUpload, File, FileValidation
from files.utils import SafeUnzip

from mkt.constants import APP_PREVIEW_SIZES
from mkt.webapps.models import AddonExcludedRegion, Webapp


log = logging.getLogger('z.mkt.developers.task')

CT_URL = (
    'https://developer.mozilla.org/docs/Web/Apps/Manifest#Serving_manifests'
)


@task
@write
def validator(upload_id, **kw):
    if not settings.VALIDATE_ADDONS:
        return None
    log.info(u'[FileUpload:%s] Validating app.' % upload_id)
    try:
        upload = FileUpload.objects.get(pk=upload_id)
    except FileUpload.DoesNotExist:
        log.info(u'[FileUpload:%s] Does not exist.' % upload_id)
        return

    try:
        validation_result = run_validator(upload.path, url=kw.get('url'))
        if upload.validation:
            # If there's any preliminary validation result, merge it with the
            # actual validation result.
            dec_prelim_result = json.loads(upload.validation)
            if 'prelim' in dec_prelim_result:
                dec_validation_result = json.loads(validation_result)
                # Merge the messages.
                dec_validation_result['messages'] += (
                    dec_prelim_result['messages'])
                # Merge the success value.
                if dec_validation_result['success']:
                    dec_validation_result['success'] = (
                        dec_prelim_result['success'])
                # Merge the error count (we only raise errors, not warnings).
                dec_validation_result['errors'] += dec_prelim_result['errors']

                # Put the validation result back into JSON.
                validation_result = json.dumps(dec_validation_result)

        upload.validation = validation_result
        upload.save()  # We want to hit the custom save().
    except Exception:
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
    log.info(u'[File:%s] Validating file.' % file_id)
    try:
        file = File.objects.get(pk=file_id)
    except File.DoesNotExist:
        log.info(u'[File:%s] Does not exist.' % file_id)
        return
    # Unlike upload validation, let the validator raise an exception if there
    # is one.
    result = run_validator(file.file_path, url=file.version.addon.manifest_url)
    return FileValidation.from_json(file, result)


def run_validator(file_path, url=None):
    """A pre-configured wrapper around the app validator."""

    with statsd.timer('mkt.developers.validator'):
        is_packaged = zipfile.is_zipfile(file_path)
        if is_packaged:
            log.info(u'Running `validate_packaged_app` for path: %s'
                     % (file_path))
            with statsd.timer('mkt.developers.validate_packaged_app'):
                return validate_packaged_app(file_path,
                    market_urls=settings.VALIDATOR_IAF_URLS,
                    timeout=settings.VALIDATOR_TIMEOUT,
                    spidermonkey=settings.SPIDERMONKEY)
        else:
            log.info(u'Running `validate_app` for path: %s' % (file_path))
            with statsd.timer('mkt.developers.validate_app'):
                return validate_app(storage.open(file_path).read(),
                    market_urls=settings.VALIDATOR_IAF_URLS,
                    url=url)


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

        log.info('Icon resizing completed for: %s' % dst)
        return True
    except Exception, e:
        log.error("Error saving addon icon: %s; %s" % (e, dst))


@task
@set_modified_on
def resize_preview(src, instance, **kw):
    """Resizes preview images and stores the sizes on the preview."""
    thumb_dst, full_dst = instance.thumbnail_path, instance.image_path
    sizes = {}
    log.info('[1@None] Resizing preview and storing size: %s' % thumb_dst)
    try:
        thumbnail_size = APP_PREVIEW_SIZES[0][:2]
        image_size = APP_PREVIEW_SIZES[1][:2]
        with storage.open(src, 'rb') as fp:
            size = Image.open(fp).size
        if size[0] > size[1]:
            # If the image is wider than tall, then reverse the wanted size
            # to keep the original aspect ratio while still resizing to
            # the correct dimensions.
            thumbnail_size = thumbnail_size[::-1]
            image_size = image_size[::-1]

        sizes['thumbnail'] = resize_image(src, thumb_dst,
                                          thumbnail_size,
                                          remove_src=False)
        sizes['image'] = resize_image(src, full_dst,
                                      image_size,
                                      remove_src=False)
        instance.sizes = sizes
        instance.save()
        log.info('Preview resized to: %s' % thumb_dst)
        return True
    except Exception, e:
        log.error("Error saving preview: %s; %s" % (e, thumb_dst))


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
                    'thumbnail': Image.open(preview.thumbnail_path).size,
                    'image': Image.open(preview.image_path).size,
                }
                preview.update(sizes=sizes)
            except Exception, err:
                log.error('Failed to find size of preview: %s, error: %s'
                          % (addon.pk, err))


def _fetch_content(url):
    with statsd.timer('developers.tasks.fetch_content'):
        try:
            res = requests.get(url, timeout=30, stream=True)

            if not 200 <= res.status_code < 300:
                statsd.incr('developers.tasks.fetch_content.error')
                raise Exception('An invalid HTTP status code was returned.')

            if not res.headers.keys():
                statsd.incr('developers.tasks.fetch_content.error')
                raise Exception('The HTTP server did not return headers.')

            statsd.incr('developers.tasks.fetch_content.success')
            return res
        except requests.RequestException as e:
            statsd.incr('developers.tasks.fetch_content.error')
            log.error('fetch_content connection error: %s' % e)
            raise Exception('The file could not be retrieved.')


class ResponseTooLargeException(Exception):
    pass


def get_content_and_check_size(response, max_size):
    # Read one extra byte. Reject if it's too big so we don't have issues
    # downloading huge files.
    content = response.iter_content(chunk_size=max_size + 1).next()
    if len(content) > max_size:
        raise ResponseTooLargeException('Too much data.')
    return content


def save_icon(webapp, content):
    tmp_dst = os.path.join(settings.TMP_PATH, 'icon', uuid.uuid4().hex)
    with storage.open(tmp_dst, 'wb') as fd:
        fd.write(content)

    dirname = webapp.get_icon_dir()
    destination = os.path.join(dirname, '%s' % webapp.id)
    remove_icons(destination)
    resize_icon(tmp_dst, destination, amo.ADDON_ICON_SIZES,
                set_modified_on=[webapp])

    # Need to set the icon type so .get_icon_url() works
    # normally submit step 4 does it through AddonFormMedia,
    # but we want to beat them to the punch.
    # resize_icon outputs pngs, so we know it's 'image/png'
    webapp.icon_type = 'image/png'
    webapp.save()


@task_with_callbacks
@write
def fetch_icon(webapp, **kw):
    """Downloads a webapp icon from the location specified in the manifest.
    Returns False if icon was not able to be retrieved
    """
    log.info(u'[1@None] Fetching icon for webapp %s.' % webapp.name)
    manifest = webapp.get_manifest_json()
    if not manifest or not 'icons' in manifest:
        # Set the icon type to empty.
        webapp.update(icon_type='')
        return

    try:
        biggest = max(int(size) for size in manifest['icons'])
    except ValueError:
        log.error('No icon to fetch for webapp "%s"' % webapp.name)
        return False

    icon_url = manifest['icons'][str(biggest)]
    if icon_url.startswith('data:image'):
        image_string = icon_url.split('base64,')[1]
        content = base64.decodestring(image_string)
    else:
        if webapp.is_packaged:
            # Get icons from package.
            if icon_url.startswith('/'):
                icon_url = icon_url[1:]
            try:
                zf = SafeUnzip(webapp.get_latest_file().file_path)
                zf.is_valid()
                content = zf.extract_path(icon_url)
            except (KeyError, forms.ValidationError):  # Not found in archive.
                log.error(u'[Webapp:%s] Icon %s not found in archive'
                          % (webapp, icon_url))
                return False
        else:
            if not urlparse.urlparse(icon_url).scheme:
                icon_url = webapp.origin + icon_url

            try:
                response = _fetch_content(icon_url)
            except Exception, e:
                log.error(u'[Webapp:%s] Failed to fetch icon for webapp: %s'
                          % (webapp, e))
                # Set the icon type to empty.
                webapp.update(icon_type='')
                return False

            try:
                content = get_content_and_check_size(
                    response, settings.MAX_ICON_UPLOAD_SIZE)
            except ResponseTooLargeException:
                log.warning(u'[Webapp:%s] Icon exceeds maximum size.' % webapp)
                return False

    log.info('Icon fetching completed for app "%s"; saving icon' % webapp.name)
    save_icon(webapp, content)


def failed_validation(*messages, **kwargs):
    """Return a validation object that looks like the add-on validator."""
    upload = kwargs.pop('upload', None)
    if upload is None or not upload.validation:
        msgs = []
    else:
        msgs = json.loads(upload.validation)['messages']

    for msg in messages:
        msgs.append({'type': 'error', 'message': msg, 'tier': 1})

    return json.dumps({'errors': sum(1 for m in msgs if m['type'] == 'error'),
                       'success': False,
                       'messages': msgs,
                       'prelim': True})


def _fetch_manifest(url, upload=None):
    def fail(message, upload=None):
        if upload is None:
            # If `upload` is None, that means we're using one of @washort's old
            # implementations that expects an exception back.
            raise Exception(message)
        upload.update(validation=failed_validation(message, upload=upload))

    try:
        response = _fetch_content(url)
    except Exception, e:
        log.error('Failed to fetch manifest from %r: %s' % (url, e))
        fail(_('No manifest was found at that URL. Check the address and try '
               'again.'), upload=upload)
        return

    ct = response.headers.get('content-type', '')
    if not ct.startswith('application/x-web-app-manifest+json'):
        fail(_('Manifests must be served with the HTTP header '
               '"Content-Type: application/x-web-app-manifest+json". See %s '
               'for more information.') % CT_URL,
             upload=upload)

    try:
        max_webapp_size = settings.MAX_WEBAPP_UPLOAD_SIZE
        content = get_content_and_check_size(response, max_webapp_size)
    except ResponseTooLargeException:
        fail(_('Your manifest must be less than %s bytes.') % max_webapp_size,
             upload=upload)
        return

    try:
        content.decode('utf_8')
    except (UnicodeDecodeError, UnicodeEncodeError), exc:
        log.info('Manifest decode error: %s: %s' % (url, exc))
        fail(_('Your manifest file was not encoded as valid UTF-8.'),
             upload=upload)
        return

    # Get the individual parts of the content type.
    ct_split = map(str.strip, ct.split(';'))
    if len(ct_split) > 1:
        # Figure out if we've got a charset specified.
        kv_pairs = dict(tuple(p.split('=', 1)) for p in ct_split[1:] if
                              '=' in p)
        if 'charset' in kv_pairs and kv_pairs['charset'].lower() != 'utf-8':
            fail(_("The manifest's encoding does not match the charset "
                   'provided in the HTTP Content-Type.'),
                 upload=upload)

    content = strip_bom(content)
    return content


@task
@write
def fetch_manifest(url, upload_pk=None, **kw):
    log.info(u'[1@None] Fetching manifest: %s.' % url)
    upload = FileUpload.objects.get(pk=upload_pk)

    content = _fetch_manifest(url, upload)
    if content is None:
        return

    upload.add_file([content], url, len(content), is_webapp=True)
    # Send the upload to the validator.
    validator(upload.pk, url=url)


@task
def subscribe_to_responsys(campaign, address, format='html', source_url='',
                           lang='', country='', **kw):
    """
    Subscribe a user to a list in responsys. There should be two
    fields within the Responsys system named by the "campaign"
    parameter: <campaign>_FLG and <campaign>_DATE.
    """

    data = {
        'LANG_LOCALE': lang,
        'COUNTRY_': country,
        'SOURCE_URL': source_url,
        'EMAIL_ADDRESS_': address,
        'EMAIL_FORMAT_': 'H' if format == 'html' else 'T',
    }

    data['%s_FLG' % campaign] = 'Y'
    data['%s_DATE' % campaign] = date.today().strftime('%Y-%m-%d')
    data['_ri_'] = settings.RESPONSYS_ID

    try:
        res = requests.get('http://awesomeness.mozilla.org/pub/rf',
                           data=urlencode(data))
        return res.status_code == 200
    except requests.RequestException:
        return False


@task
def region_email(ids, regions, **kw):
    region_names = regions = sorted([unicode(r.name) for r in regions])

    # Format the region names with commas and fanciness.
    if len(regions) == 2:
        suffix = 'two'
        region_names = ' '.join([regions[0], _(u'and'), regions[1]])
    else:
        if len(regions) == 1:
            suffix = 'one'
        elif len(regions) > 2:
            suffix = 'many'
            region_names[-1] = _(u'and') + ' ' + region_names[-1]
        region_names = ', '.join(region_names)

    log.info('[%s@%s] Emailing devs about new region(s): %s.' %
             (len(ids), region_email.rate_limit, region_names))

    for id_ in ids:
        log.info('[Webapp:%s] Emailing devs about new region(s): %s.' %
                (id_, region_names))

        product = Webapp.objects.get(id=id_)
        to = set(product.authors.values_list('email', flat=True))

        if len(regions) == 1:
            subject = _(
                u'{region} region added to the Firefox Marketplace').format(
                    region=regions[0])
        else:
            subject = _(u'New regions added to the Firefox Marketplace')

        dev_url = absolutify(product.get_dev_url('edit'),
                             settings.SITE_URL) + '#details'
        context = {'app': product.name,
                   'regions': region_names,
                   'dev_url': dev_url}
        send_mail_jinja('%s: %s' % (product.name, subject),
                        'developers/emails/new_regions_%s.ltxt' % suffix,
                        context, recipient_list=to,
                        perm_setting='app_regions')


@task
@write
def region_exclude(ids, regions, **kw):
    region_names = ', '.join(sorted([unicode(r.name) for r in regions]))

    log.info('[%s@%s] Excluding new region(s): %s.' %
             (len(ids), region_exclude.rate_limit, region_names))

    for id_ in ids:
        log.info('[Webapp:%s] Excluding region(s): %s.' %
                 (id_, region_names))
        for region in regions:
            # Already excluded? Swag!
            AddonExcludedRegion.objects.get_or_create(addon_id=id_,
                                                      region=region.id)


@task
def save_test_plan(f, filename, addon):
    dst_root = os.path.join(settings.ADDONS_PATH, str(addon.id))
    dst = os.path.join(dst_root, filename)
    with open(dst, 'wb+') as destination:
        for chunk in f.chunks():
            destination.write(chunk)
