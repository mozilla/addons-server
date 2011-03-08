import os
import shutil
import stat
import time

import cronjobs
import commonware.log

from django.conf import settings


log = commonware.log.getLogger('z.cron')


@cronjobs.register
def cleanup_extracted_file():
    log.info('Removing extracted files for file viewer.')
    root = os.path.join(settings.TMP_PATH, 'file_viewer')
    for path in os.listdir(root):
        path = os.path.join(root, path)
        age = time.time() - os.stat(path)[stat.ST_CTIME]
        if (age) > (60 * 60):
            log.info('Removing extracted files: %s, %dsecs old.' % (path, age))
            shutil.rmtree(path)
