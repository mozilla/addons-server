import os
import shutil

from datetime import datetime

from django.conf import settings

import olympia.core.logger

from olympia.files.models import FileValidation


def cleanup_extracted_file():
    log.info('Removing extracted files for file viewer.')
    root = os.path.join(settings.TMP_PATH, 'file_viewer')

    for day in os.listdir(root):
        full = os.path.join(root, day)

        today = datetime.now().strftime('%m%d')

        if day != today:
            log.debug('Removing extracted files: %s, from %sd.' % (full, day))

            # Remove all files.
            # No need to remove any caches since we are deleting files from
            # yesterday or before and the cache-keys are only valid for an
            # hour. There might be a slight edge-case but that's reasonable.
            shutil.rmtree(full)


def cleanup_validation_results():
    """Will remove all validation results.  Used when the validator is
    upgraded and results may no longer be relevant."""
    # With a large enough number of objects not using no_cache() tracebacks
    all = FileValidation.objects.no_cache().all()
    log.info('Removing %s old validation results.' % (all.count()))
    all.delete()
