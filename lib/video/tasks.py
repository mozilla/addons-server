import logging
import os
import shutil

from celeryutils import task

import amo
from amo.decorators import set_modified_on
from lib.video.ffmpeg import Video

log = logging.getLogger('z.devhub.task')


@task
@set_modified_on
def resize_video(src, instance, *kw):
    """
    Given a preview object and a file somewhere: encode into the full
    preview size and generate a thumbnail.
    """
    log.info('[1@None] Encoding video %s' % instance.pk)
    video = Video(src)
    video.get_meta()
    if not video.is_valid():
        log.info('Video is not valid for %s' % instance.pk)
        return

    # Do the video first, this can take a bit.
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
        # encoded successfully.
        os.remove(video_file)
        log.info('Error making thumbnail for %s' % instance.pk)
        return

    shutil.move(thumbnail_file, instance.thumbnail_path)
    shutil.move(video_file, instance.image_path)
    instance.sizes = {'thumbnail': amo.ADDON_PREVIEW_SIZES[0],
                      'image': amo.ADDON_PREVIEW_SIZES[1]}
    instance.save()
    log.info('Completed encoding video: %s' % instance.pk)
