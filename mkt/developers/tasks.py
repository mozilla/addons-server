# -*- coding: utf-8 -*-
import base64
import json
import logging
import os
import socket
import sys
import traceback
import urllib2
import urlparse
import uuid
import zipfile
from datetime import date

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils.http import urlencode

from appvalidator import validate_app, validate_packaged_app
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

from mkt.webapps.models import AddonExcludedRegion, Webapp


log = logging.getLogger('z.mkt.developers.task')


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
        upload.validation = run_validator(upload.path)
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
    log.info(u'[File:%s] Validating file.' % file_id)
    try:
        file = File.objects.get(pk=file_id)
    except File.DoesNotExist:
        log.info(u'[File:%s] Does not exist.' % file_id)
        return
    # Unlike upload validation, let the validator raise an exception if there
    # is one.
    result = run_validator(file.file_path)
    return FileValidation.from_json(file, result)


def run_validator(file_path):
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
                    market_urls=settings.VALIDATOR_IAF_URLS)


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
                    'thumbnail':  Image.open(preview.thumbnail_path).size,
                    'image':  Image.open(preview.image_path).size,
                }
                preview.update(sizes=sizes)
            except Exception, err:
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
        return urllib2.urlopen(url, timeout=5)
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


def get_content_and_check_size(response, max_size, error_message):
    # Read one extra byte. Reject if it's too big so we don't have issues
    # downloading huge files.
    content = response.read(max_size + 1)
    if len(content) > max_size:
        raise Exception(error_message % max_size)
    return content


def check_manifest_encoding(url, content):
    # TODO(Kumar) check for encoding hints in response headers
    # and store an encoding hint on the file upload object
    try:
        content.decode('utf8')
    except UnicodeDecodeError, exc:
        log.info('Manifest decode error: %s: %s' % (url, exc))
        exc.message = _('Your manifest file was not encoded as valid UTF-8')
        raise


def save_icon(webapp, content):
    tmp_dst = os.path.join(settings.TMP_PATH, 'icon', uuid.uuid4().hex)
    with storage.open(tmp_dst, 'wb') as fd:
        fd.write(content)

    dirname = webapp.get_icon_dir()
    destination = os.path.join(dirname, '%s' % webapp.id)
    remove_icons(destination)
    resize_icon.delay(tmp_dst, destination, amo.ADDON_ICON_SIZES,
                      set_modified_on=[webapp])

    # Need to set the icon type so .get_icon_url() works
    # normally submit step 4 does it through AddonFormMedia,
    # but we want to beat them to the punch.
    # resize_icon outputs pngs, so we know it's 'image/png'
    webapp.icon_type = 'image/png'
    webapp.save()


@task
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
        biggest = max([int(size) for size in manifest['icons']])
    except ValueError:
        return

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
                return
        else:
            if not urlparse.urlparse(icon_url).scheme:
                icon_url = webapp.origin + icon_url

            try:
                response = _fetch_content(icon_url)
            except Exception, e:
                log.error(u'[Webapp:%s] Failed to fetch icon for webapp: %s'
                          % (webapp, e.message))
                # Set the icon type to empty.
                webapp.update(icon_type='')
                return

            size_error_message = _('Your icon must be less than %s bytes.')
            content = get_content_and_check_size(response,
                                                 settings.MAX_ICON_UPLOAD_SIZE,
                                                 size_error_message)

    save_icon(webapp, content)


def _fetch_manifest(url):
    try:
        response = _fetch_content(url)
    except Exception, e:
        log.error('Failed to fetch manifest from %r: %s' % (url, e))
        raise Exception('No manifest was found at that URL.')

    size_error_message = _('Your manifest must be less than %s bytes.')
    content = get_content_and_check_size(response,
                                         settings.MAX_WEBAPP_UPLOAD_SIZE,
                                         size_error_message)
    content = strip_bom(content)
    check_manifest_encoding(url, content)
    return content


@task
@write
def fetch_manifest(url, upload_pk=None, **kw):
    log.info(u'[1@None] Fetching manifest: %s.' % url)
    upload = FileUpload.objects.get(pk=upload_pk)

    try:
        content = _fetch_manifest(url)
    except Exception, e:
        # Drop a message in the validation slot and bail.
        upload.update(validation=failed_validation(e.message))
        return

    upload.add_file([content], url, len(content), is_webapp=True)
    # Send the upload to the validator.
    validator(upload.pk)


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
        res = urllib2.urlopen('http://awesomeness.mozilla.org/pub/rf',
                              data=urlencode(data))
        return res.code == 200
    except urllib2.URLError:
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
            subject = _(u'{region} region added to the Firefox Marketplace'
                ).format(region=regions[0])
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
            AddonExcludedRegion.objects.create(addon_id=id_, region=region.id)
