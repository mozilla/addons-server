import os

import requests

from django.conf import settings
from django_statsd.clients import statsd

import olympia.core.logger

from olympia.amo.celery import task
from olympia.constants.scanners import SCANNERS, CUSTOMS
from olympia.files.models import FileUpload

from .models import ScannersResult

log = olympia.core.logger.getLogger('z.scanners.task')


def run_scanner(upload_pk, scanner, api_url, api_key):
    """
    Run a scanner on a FileUpload via RPC and store the results.
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
        if not os.path.exists(upload.path):
            raise ValueError('Path "{}" is not a file or directory or does '
                             'not exist.' .format(upload.path))

        result = ScannersResult()
        result.upload = upload
        result.scanner = scanner

        with statsd.timer('devhub.{}'.format(scanner_name)):
            headers = {'Authorization': 'Bearer {}'.format(api_key)}
            with open(upload.path, 'rb') as xpi:
                response = requests.post(url=api_url,
                                         files={'xpi': xpi},
                                         headers=headers)

        results = response.json()
        if 'error' in results:
            raise ValueError(results)

        result.results = results
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
        api_url=settings.CUSTOMS_API_URL,
        api_key=settings.CUSTOMS_API_KEY
    )
