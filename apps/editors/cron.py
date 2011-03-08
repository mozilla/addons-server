import os
import shutil
import stat
import time
import zipfile

import cronjobs
from celeryutils import task
import commonware.log

from django.conf import settings


log = commonware.log.getLogger('z.cron')


@cronjobs.register
def cleanup_extracted_file():
    log.info('Cleanup extracted file')
    root = os.path.join(settings.TMP_PATH, 'file_viewer')
    for path in os.listdir(root):
        path = os.path.join(root, path)
        if (time.time() - os.stat(path)[stat.ST_CTIME]) > (60 * 60):
            log.info('Removing tree: %s' % path)
            shutil.rmtree(path)
