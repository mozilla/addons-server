import hashlib
import os
import shutil
import stat
import time

from django.conf import settings
from django.core.cache import cache

import commonware.log
import cronjobs

from olympia.files.models import FileValidation

log = commonware.log.getLogger('z.cron')


@cronjobs.register
def cleanup_extracted_file():
    log.info('Removing extracted files for file viewer.')
    root = os.path.join(settings.TMP_PATH, 'file_viewer')
    for path in os.listdir(root):
        full = os.path.join(root, path)
        age = time.time() - os.stat(full)[stat.ST_ATIME]
        if age > 60 * 60:
            log.debug('Removing extracted files: %s, %dsecs old.' %
                      (full, age))
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


@cronjobs.register
def cleanup_validation_results():
    """Will remove all validation results.  Used when the validator is
    upgraded and results may no longer be relevant."""
    # With a large enough number of objects not using no_cache() tracebacks
    all = FileValidation.objects.no_cache().all()
    log.info('Removing %s old validation results.' % (all.count()))
    all.delete()
