import logging
import os
import shutil

from django.conf import settings

import amo
from amo.celery import task
from amo.decorators import set_modified_on
from lib.video import library
import waffle

log = logging.getLogger('z.devhub.task')
time_limits = settings.CELERY_TIME_LIMITS['lib.video.tasks.resize_video']


# Video decoding can take a while, so let's increase these limits.
@task(time_limit=time_limits['hard'], soft_time_limit=time_limits['soft'])
@set_modified_on
def resize_video(src, instance, user=None, **kw):
    """Try and resize a video and cope if it fails."""
    try:
        result = _resize_video(src, instance, **kw)
    except Exception, err:
        log.error('Error on processing video: %s' % err)
        _resize_error(src, instance, user)
        raise

    if not result:
        log.error('Error on processing video, _resize_video not True.')
        _resize_error(src, instance, user)

    log.info('Video resize complete.')
    return


def _resize_error(src, instance, user):
    """An error occurred in processing the video, deal with that approp."""
    amo.log(amo.LOG.VIDEO_ERROR, instance, user=user)
    instance.delete()


def _resize_video(src, instance, **kw):
    """
    Given a preview object and a file somewhere: encode into the full
    preview size and generate a thumbnail.
    """
    log.info('[1@None] Encoding video %s' % instance.pk)
    lib = library
    if not lib:
        log.info('Video library not available for %s' % instance.pk)
        return

    video = lib(src)
    video.get_meta()
    if not video.is_valid():
        log.info('Video is not valid for %s' % instance.pk)
        return

    # Do the thumbnail next, this will be the signal that the
    # encoding has finished.
    try:
        thumbnail_file = video.get_screenshot(amo.ADDON_PREVIEW_SIZES[0])
    except Exception:
        log.info('Error making thumbnail for %s' % instance.pk, exc_info=True)
        return

    for path in (instance.thumbnail_path, instance.image_path):
        dirs = os.path.dirname(path)
        if not os.path.exists(dirs):
            os.makedirs(dirs)

    shutil.move(thumbnail_file, instance.thumbnail_path)
    shutil.copyfile(src, instance.image_path)

    instance.sizes = {'thumbnail': amo.ADDON_PREVIEW_SIZES[0],
                      'image': amo.ADDON_PREVIEW_SIZES[1]}
    instance.save()
    log.info('Completed encoding video: %s' % instance.pk)
    return True
