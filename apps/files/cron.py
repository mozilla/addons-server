import hashlib
import os
import shutil
import stat
import time

from django.conf import settings
from django.core.cache import cache

import cronjobs
import commonware.log


log = commonware.log.getLogger('z.cron')


@cronjobs.register
def cleanup_extracted_file():
    log.info('Removing extracted files for file viewer.')
    root = os.path.join(settings.TMP_PATH, 'file_viewer')
    for path in os.listdir(root):
        full = os.path.join(root, path)
        age = time.time() - os.stat(full)[stat.ST_ATIME]
        if (age) > (60 * 60):
            log.info('Removing extracted files: %s, %dsecs old.' % (full, age))
            shutil.rmtree(full)
            # Nuke out the file and diff caches when the file gets removed.
            id = os.path.basename(path)
            try:
                int(id)
            except ValueError:
                continue

            key = hashlib.md5()
            key.update(str(id))
            cache.delete('%s:memoize:%s:%s' % (settings.CACHE_PREFIX,
                                               'file-viewer', key.hexdigest()))
            log.info('Removing cache file-viewer cache entries for: %s' % id)


@cronjobs.register
def cleanup_watermarked_file():
    log.info('Removing watermarked files.')
    root = settings.WATERMARKED_ADDONS_PATH
    if not os.path.exists(root):
        os.makedirs(root)

    for path in os.listdir(root):
        folder = os.path.join(root, path)
        for file in os.listdir(folder):
            full = os.path.join(root, path, file)
            age = time.time() - os.stat(full)[stat.ST_ATIME]
            if age > settings.WATERMARK_CLEANUP_SECONDS:
                log.info('Removing watermarked file: %s, %dsecs.'
                         % (full, age))
                os.remove(full)

        if not os.listdir(folder):
            shutil.rmtree(folder)
