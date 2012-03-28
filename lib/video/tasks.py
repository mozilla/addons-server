import logging
import os
import shutil

from celeryutils import task

import amo
from amo.decorators import set_modified_on
from lib.video.ffmpeg import Video
import waffle

log = logging.getLogger('z.devhub.task')


@task
@set_modified_on
def resize_video(src, instance, **kw):
    """
    Given a preview object and a file somewhere: encode into the full
    preview size and generate a thumbnail.
    """
    log.info('[1@None] Encoding video %s' % instance.pk)
    video = Video(src)
    if not video.encoder_available():
        log.info('Video encoder not available for %s' % instance.pk)
        return

    video.get_meta()
    if not video.is_valid():
        log.info('Video is not valid for %s' % instance.pk)
        return

    if waffle.switch_is_active('video-encode'):
        # Do the video encoding.
        try:
            video_file = video.get_encoded(amo.ADDON_PREVIEW_SIZES[1])
        except Exception:
            log.info('Error encoding video for %s' % instance.pk)
            return

    # Do the thumbnail next, this will be the signal that the
    # encoding has finished.
    try:
        thumbnail_file = video.get_screenshot(amo.ADDON_PREVIEW_SIZES[0])
    except Exception:
        # We'll have this file floating around because the video
        # encoded successfully, or something has gone wrong in which case
        # we don't want the file around anyway.
        if waffle.switch_is_active('video-encode'):
            os.remove(video_file)
        log.info('Error making thumbnail for %s' % instance.pk)
        return

    for path in (instance.thumbnail_path, instance.image_path):
        dirs = os.path.dirname(path)
        if not os.path.exists(dirs):
            os.makedirs(dirs)

    shutil.move(thumbnail_file, instance.thumbnail_path)
    if waffle.switch_is_active('video-encode'):
        # Move the file over, removing the temp file.
        shutil.move(video_file, instance.image_path)
    else:
        # We didn't re-encode the file.
        shutil.copyfile(src, instance.image_path)

    instance.sizes = {'thumbnail': amo.ADDON_PREVIEW_SIZES[0],
                      'image': amo.ADDON_PREVIEW_SIZES[1]}
    instance.save()
    log.info('Completed encoding video: %s' % instance.pk)
