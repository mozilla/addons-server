import os
import uuid
from datetime import datetime

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.template.defaultfilters import filesizeformat

import commonware.log
import waffle
from PIL import Image
from tower import ugettext as _

import amo
from mkt.constants import APP_PREVIEW_MINIMUMS
from lib.video import library as video_library

from editors.models import EscalationQueue
from mkt.comm.utils import create_comm_note
from mkt.constants import comm
from mkt.reviewers.utils import send_mail
from amo.helpers import absolutify
from amo.urlresolvers import reverse

log = commonware.log.getLogger('z.devhub')


def uri_to_pk(uri):
    """
    Convert a resource URI to the primary key of the resource.
    """
    return uri.rstrip('/').split('/')[-1]


def check_upload(file_obj, upload_type, content_type):
    errors = []
    upload_hash = ''
    is_icon = upload_type == 'icon'
    is_preview = upload_type == 'preview'
    is_video = content_type in amo.VIDEO_TYPES

    if not any([is_icon, is_preview, is_video]):
        raise ValueError('Unknown upload type.')

    # By pushing the type onto the instance hash, we can easily see what
    # to do with the file later.
    ext = content_type.replace('/', '-')
    upload_hash = '%s.%s' % (uuid.uuid4().hex, ext)
    loc = os.path.join(settings.TMP_PATH, upload_type, upload_hash)

    with storage.open(loc, 'wb') as fd:
        for chunk in file_obj:
            fd.write(chunk)

    # A flag to prevent us from attempting to open the image with PIL.
    do_not_open = False

    if is_video:
        if not video_library:
            errors.append(_('Video support not enabled.'))
        else:
            video = video_library(loc)
            video.get_meta()
            if not video.is_valid():
                errors.extend(video.errors)

    else:
        check = amo.utils.ImageCheck(file_obj)
        if (not check.is_image() or
            content_type not in amo.IMG_TYPES):
            do_not_open = True
            if is_icon:
                errors.append(_('Icons must be either PNG or JPG.'))
            else:
                errors.append(_('Images must be either PNG or JPG.'))

        if check.is_animated():
            do_not_open = True
            if is_icon:
                errors.append(_('Icons cannot be animated.'))
            else:
                errors.append(_('Images cannot be animated.'))

    max_size = (settings.MAX_ICON_UPLOAD_SIZE if is_icon else
                settings.MAX_VIDEO_UPLOAD_SIZE if is_video else
                settings.MAX_IMAGE_UPLOAD_SIZE if is_preview else None)

    if max_size and file_obj.size > max_size:
        do_not_open = True
        if is_icon or is_video:
            errors.append(_('Please use files smaller than %s.') %
                filesizeformat(max_size))

    if (is_icon or is_preview) and not is_video and not do_not_open:
        file_obj.seek(0)
        try:
            im = Image.open(file_obj)
            im.verify()
        except IOError:
            if is_icon:
                errors.append(_('Icon could not be opened.'))
            elif is_preview:
                errors.append(_('Preview could not be opened.'))
        else:
            size_x, size_y = im.size
            if is_icon:
                # TODO: This should go away when we allow uploads for
                # individual icon sizes.
                if size_x < 128 or size_y < 128:
                    errors.append(_('Icons must be at least 128px by 128px.'))

                if size_x != size_y:
                    errors.append(_('Icons must be square.'))

            elif is_preview:
                if (size_x < APP_PREVIEW_MINIMUMS[0] or
                    size_y < APP_PREVIEW_MINIMUMS[1]) and (
                        size_x < APP_PREVIEW_MINIMUMS[1] or
                        size_y < APP_PREVIEW_MINIMUMS[0]):
                    errors.append(
                        # L10n: {0} and {1} are the height/width of the preview
                        # in px.
                        _('App previews must be at least {0}px by {1}px or '
                          '{1}px by {0}px.').format(*APP_PREVIEW_MINIMUMS))

    return errors, upload_hash


def handle_vip(addon, version, user):
    msg = u'VIP app updated'

    # Add to escalation queue
    EscalationQueue.objects.get_or_create(addon=addon)

    # Create comm note
    create_comm_note(addon, version, user, msg, note_type=comm.ESCALATION,
                     perms={'developer': False})

    # Log action
    amo.log(amo.LOG.ESCALATION_VIP_APP, addon, version, created=datetime.now(),
            details={'comments': msg})
    log.info(u'[app:%s] escalated - %s' % (addon.name, msg))

    # Special senior reviewer email.
    if not waffle.switch_is_active('comm-dashboard'):
        context = {'name': addon.name,
                   'review_url': absolutify(reverse('reviewers.apps.review',
                                                     args=[addon.app_slug],
                                                     add_prefix=False)),
                   'SITE_URL': settings.SITE_URL}
        send_mail(u'%s: %s' % (msg, addon.name),
                   'developers/emails/vip_escalation.ltxt', context,
                   [settings.MKT_SENIOR_EDITORS_EMAIL])
