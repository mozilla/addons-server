import os
import uuid

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.template.defaultfilters import filesizeformat

from tower import ugettext as _
import waffle

import amo
import mkt.constants.submit as submit_constants
from lib.video import library as video_library


def check_upload(file_obj, upload_type, content_type):
    errors = []
    upload_hash = ''
    is_icon = upload_type == 'icon'
    is_video = (content_type in amo.VIDEO_TYPES and
                waffle.switch_is_active('video-upload'))

    # By pushing the type onto the instance hash, we can easily see what
    # to do with the file later.
    ext = content_type.replace('/', '-')
    upload_hash = '%s.%s' % (uuid.uuid4().hex, ext)
    loc = os.path.join(settings.TMP_PATH, upload_type, upload_hash)

    with storage.open(loc, 'wb') as fd:
        for chunk in file_obj:
            fd.write(chunk)

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
            if is_icon:
                errors.append(_('Icons must be either PNG or JPG.'))
            else:
                errors.append(_('Images must be either PNG or JPG.'))
        elif is_icon:
            # The upload is an image and it's intended to be an icon.
            icon_width, icon_height = check.img.size
            min_width, min_height = submit_constants.APP_ICON_MIN_SIZE
            if icon_width < min_width or icon_height < min_height:
                errors.append(_('The icon must be at least 128x128px.'))

        if check.is_animated():
            if is_icon:
                errors.append(_('Icons cannot be animated.'))
            else:
                errors.append(_('Images cannot be animated.'))

    max_size = (settings.MAX_ICON_UPLOAD_SIZE if is_icon else
                settings.MAX_VIDEO_UPLOAD_SIZE if is_video else None)

    if max_size and file_obj.size > max_size:
        if is_icon or is_video:
            errors.append(_('Please use files smaller than %s.') %
                filesizeformat(max_size))

    return errors, upload_hash

