# -*- coding: utf-8 -*-
import base64
import colorsys
import json
import logging
import os
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

from mkt.constants import APP_IMAGE_SIZES, APP_PREVIEW_SIZES
from mkt.webapps.models import AddonExcludedRegion, ImageAsset, Webapp


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
                                          APP_PREVIEW_SIZES[0][:2],
                                          remove_src=False)
        sizes['image'] = resize_image(src, full_dst,
                                      APP_PREVIEW_SIZES[1][:2],
                                      remove_src=False)
        instance.sizes = sizes
        instance.save()
        return True
    except Exception, e:
        log.error("Error saving preview: %s" % e)


@task
@set_modified_on
def resize_imageasset(src, full_dst, size, **kw):
    """Resizes image assets and puts them where they need to be."""

    log.info('[1@None] Resizing image asset: %s' % full_dst)
    try:
        hue = 0
        with storage.open(src, 'rb') as fp:
            im = Image.open(fp)
            im = im.convert('RGBA')
            im = im.resize(size)

        with storage.open(full_dst, 'wb') as fp:
            im.save(fp, 'png')

        # If we pass in the image asset instance ID, get the hue of the new
        # asset and update the asset instance.
        instance_id = kw.pop('instance', None)
        if instance_id is not None:
            ImageAsset.objects.get(pk=instance_id).update(hue=get_hue(im))
        return True
    except Exception, e:
        log.error('Error saving image asset: %s' % e)


def get_hue(image):
    """Return the most common hue of the image."""
    hues = [0 for x in range(256)]
    # Iterate each pixel. Count each hue value in `hues`.
    for pixel in image.getdata():
        # Ignore greyscale pixels.
        if pixel[0] == pixel[1] and pixel[1] == pixel[2]:
            continue
        # Ignore non-opaque pixels.
        if pixel[3] < 255:
            continue
        h, l, s = colorsys.rgb_to_hls(*[x / 255.0 for x in pixel[:3]])
        # Get a tally of the hue for that image.
        hues[int(h * 255)] += 1

    return hues.index(max(hues))


def _generate_image_asset_backdrop(hue, size=None):
    with storage.open(os.path.join(settings.MEDIA_ROOT,
                                   'img/hub/assetback.png')) as assetback:
        im = Image.open(assetback)
        if size:
            im = im.resize(size)
        im_width = im.size[0]

        # Change the hue of the background by iterating each pixel.
        for i, px in enumerate(im.getdata()):
            # Get the HLS value for the pixel
            h, l, s = colorsys.rgb_to_hls(*[x / 255.0 for x in px[:3]])
            # Convert back to RGB
            px = tuple([int(x * 255) for x in
                        colorsys.hls_to_rgb(hue, l, s)])
            # Put the RGB value back in the pixel
            im.putpixel((i % im_width, i / im_width), px)

    return im


@task_with_callbacks
@set_modified_on
def generate_image_assets(addon, **kw):
    """Creates default image assets for each asset size for an app."""

    try:
        with storage.open(os.path.join(addon.get_icon_dir(),
                                       '%s-128.png' % addon.id)) as raw_icon:
            icon = Image.open(raw_icon)
            icon.load()
    except IOError:
        log.error('[1@None] Could not read 128x128 icon for %s' % addon.id)
        try:
            with storage.open(os.path.join(
                    addon.get_icon_dir(), '%s-64.png' % addon.id)) as raw_icon:
                icon = Image.open(raw_icon)
                icon.load()
        except IOError:
            log.error('[1@None] Could not read 64x64 icon for %s' % addon.id)
            return None

    # The index of the hue with the most tallies is the hue of the icon. Divide
    # by 255.0 because colorsys works with 0-1.0 floats.
    icon_hue = get_hue(icon) / 255.0
    biggest_size = max(
        APP_IMAGE_SIZES, key=lambda x: x['size'][0] * x['size'][1])['size']

    backdrop = _generate_image_asset_backdrop(icon_hue, biggest_size)

    # Sometimes you want to regenerate only assets of a particular type.
    slug = kw.get('slug')

    for asset in APP_IMAGE_SIZES:
        if slug and slug != asset['slug']:
            continue
        try:
            generate_image_asset(addon, asset, icon, hue=icon_hue,
                                 backdrop=backdrop.copy(), **kw)
        except IOError:
            log.error('[1@None] Could not write asset %s for %s' %
                          (asset['slug'], addon.id))
            break
        except Exception, e:
            log.error('[1@None] Could not generate asset %s for %s: %s' %
                          (asset['slug'], addon.id, str(e)))


def generate_image_asset(addon, asset, icon, **kw):
    """
    Generate the default image for a single image asset (`asset`) for `addon`.
    """
    log.info('[1@None] Generating image asset %s for %s' %
                 (asset['slug'], addon.id))
    image_asset, created = ImageAsset.objects.get_or_create(addon=addon,
                                                            slug=asset['slug'])

    hue = int(kw.pop('hue', 0) * 360)
    if image_asset.hue != hue:
        image_asset.hue = hue
        image_asset.save()

    backdrop = kw.pop('backdrop')
    if asset['has_background']:
        im = backdrop.resize(asset['size'], Image.ANTIALIAS)
    else:
        im = Image.new('RGBA', asset['size'])

    # Get a copy of the icon.
    asset_icon = icon.copy()

    # The icon will be 75% of the size of the shortest edge of the asset if
    # larger than 32px.
    min_edge = min(asset['size'])
    if min_edge > 32:
        min_edge = int(min_edge * 0.75)

    if min_edge < asset_icon.size[0]:
        asset_icon = asset_icon.resize((min_edge, min_edge), Image.ANTIALIAS)

    # Center the icon in the asset.
    im.paste(asset_icon,
             tuple((x / 2 - y / 2) for x, y in
                   zip(asset['size'], asset_icon.size)),
             asset_icon)

    with storage.open(image_asset.image_path, 'wb') as fp:
        im.save(fp)


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
            return urllib2.urlopen(url, timeout=30)
        except urllib2.HTTPError, e:
            raise Exception(
                _('%s responded with %s (%s).') % (url, e.code, e.msg))
        except urllib2.URLError, e:
            # Unpack the URLError to try and find a useful message.
            raise Exception(_('The file could not be retrieved.'))


class ResponseTooLargeException(Exception):
    pass


def get_content_and_check_size(response, max_size):
    # Read one extra byte. Reject if it's too big so we don't have issues
    # downloading huge files.
    content = response.read(max_size + 1)
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
    resize_icon.delay(tmp_dst, destination, amo.ADDON_ICON_SIZES,
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


CT_URL = 'https://developer.mozilla.org/en/Apps/Manifest#Serving_manifests'
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

    ct = response.headers.get('Content-Type', '')
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
