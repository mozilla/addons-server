import os
import uuid

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.template.defaultfilters import filesizeformat

from PIL import Image
from tower import ugettext as _
import waffle

import amo
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
                settings.MAX_VIDEO_UPLOAD_SIZE if is_video else None)

    if max_size and file_obj.size > max_size:
        do_not_open = True
        if is_icon or is_video:
            errors.append(_('Please use files smaller than %s.') %
                filesizeformat(max_size))

    if is_icon and not do_not_open:
        file_obj.seek(0)
        try:
            im = Image.open(file_obj)
        except IOError:
            errors.append(_('Icon could not be opened'))
        else:
            size_x, size_y = im.size
            if size_x < 128 or size_y < 128:
                errors.append(_('Icons must be at least 128px by 128px.'))

    return errors, upload_hash

