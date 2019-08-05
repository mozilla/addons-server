import json
import os
import subprocess
import tempfile

from django.utils.encoding import force_text
from django_statsd.clients import statsd

import olympia.core.logger

from olympia.amo.celery import task
from olympia.constants.scanners import SCANNERS, CUSTOMS
from olympia.files.models import FileUpload

from .models import ScannersResult

log = olympia.core.logger.getLogger('z.scanners.task')


def run_scanner(upload_pk, scanner, get_args):
    """
    Run a scanner on a FileUpload and store the results.
    """
    scanner_name = dict(SCANNERS).get(scanner)
    log.info('Starting scanner "%s" task for FileUpload %s.', scanner_name,
             upload_pk)

    upload = FileUpload.objects.get(pk=upload_pk)

    if not upload.path.endswith('.xpi'):
        log.info('Not running scanner "%s" for FileUpload %s, it is not a xpi '
                 'file.', scanner_name, upload_pk)
        return

    try:
        result = ScannersResult()
        result.upload = upload
        result.scanner = scanner

        if not os.path.exists(upload.path):
            raise ValueError('Path "{}" is not a file or directory or does '
                             'not exist.' .format(upload.path))

        stdout, stderr = (tempfile.TemporaryFile(), tempfile.TemporaryFile())

        with statsd.timer('devhub.{}'.format(scanner_name)):
            process = subprocess.Popen(
                get_args(upload.path),
                stdout=stdout,
                stderr=stderr,
                # Default but explicitly set to make sure we don't open a
                # shell.
                shell=False
            )

            process.wait()

            stdout.seek(0)
            stderr.seek(0)

            output, error = stdout.read(), stderr.read()

            # Make sure we close all descriptors, otherwise they'll hang around
            # and could cause a nasty exception.
            stdout.close()
            stderr.close()

        if error:
            raise ValueError(error)

        result.results = json.loads(force_text(output))
        result.save()

        log.info('Ending scanner "%s" task for FileUpload %s.', scanner_name,
                 upload_pk)
    except Exception:
        # We log the exception but we do not raise to avoid perturbing the
        # submission flow.
        log.exception('Error in scanner "%s" task for FileUpload %s.',
                      scanner_name, upload_pk)


@task
def run_customs(upload_pk):
    """
    Run the customs scanner on a FileUpload and store the results.

    This task is intended to be run as part of the submission process only.
    When a version is created from a FileUpload, the files are removed. In
    addition, we usually delete old FileUpload entries after 180 days.
    """
    return run_scanner(
        upload_pk,
        scanner=CUSTOMS,
        get_args=lambda upload_path: [
            '/deps/node_modules/.bin/customs',
            'scan',
            upload_path,
            '--format=json'
        ]
    )
