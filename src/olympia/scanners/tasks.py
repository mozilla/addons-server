import os

import requests
import yara

from django.conf import settings
from django_statsd.clients import statsd

import olympia.core.logger

from olympia.constants.scanners import SCANNERS, CUSTOMS, WAT, YARA
from olympia.devhub.tasks import validation_task
from olympia.files.models import FileUpload
from olympia.files.utils import SafeZip

from .models import ScannerResult

log = olympia.core.logger.getLogger('z.scanners.task')


def run_scanner(results, upload_pk, scanner, api_url, api_key):
    """
    Run a scanner on a FileUpload via RPC and store the results.

    - `results` are the validation results passed in the validation chain. This
       task is a validation task, which is why it must receive the validation
       results as first argument.
    - `upload_pk` is the FileUpload ID.
    """
    scanner_name = SCANNERS.get(scanner)
    log.info('Starting scanner "%s" task for FileUpload %s.', scanner_name,
             upload_pk)

    if not results['metadata']['is_webextension']:
        log.info('Not running scanner "%s" for FileUpload %s, it is not a '
                 'webextension.', scanner_name, upload_pk)
        return results

    upload = FileUpload.objects.get(pk=upload_pk)

    try:
        if not os.path.exists(upload.path):
            raise ValueError('File "{}" does not exist.' .format(upload.path))

        scanner_result = ScannerResult(upload=upload, scanner=scanner)

        with statsd.timer('devhub.{}'.format(scanner_name)):
            json_payload = {
                'api_key': api_key,
                'download_url': upload.get_authenticated_download_url(),
            }
            response = requests.post(url=api_url,
                                     json=json_payload,
                                     timeout=settings.SCANNER_TIMEOUT)

        try:
            data = response.json()
        except ValueError:
            # Log the response body when JSON decoding has failed.
            raise ValueError(response.text)

        if response.status_code != 200 or 'error' in data:
            raise ValueError(data)

        scanner_result.results = data
        scanner_result.save()

        statsd.incr('devhub.{}.success'.format(scanner_name))
        log.info('Ending scanner "%s" task for FileUpload %s.', scanner_name,
                 upload_pk)
    except Exception:
        statsd.incr('devhub.{}.failure'.format(scanner_name))
        # We log the exception but we do not raise to avoid perturbing the
        # submission flow.
        log.exception('Error in scanner "%s" task for FileUpload %s.',
                      scanner_name, upload_pk)

    return results


@validation_task
def run_customs(results, upload_pk):
    """
    Run the customs scanner on a FileUpload and store the results.

    This task is intended to be run as part of the submission process only.
    When a version is created from a FileUpload, the files are removed. In
    addition, we usually delete old FileUpload entries after 180 days.

    - `results` are the validation results passed in the validation chain. This
       task is a validation task, which is why it must receive the validation
       results as first argument.
    - `upload_pk` is the FileUpload ID.
    """
    return run_scanner(
        results,
        upload_pk,
        scanner=CUSTOMS,
        api_url=settings.CUSTOMS_API_URL,
        api_key=settings.CUSTOMS_API_KEY
    )


@validation_task
def run_wat(results, upload_pk):
    """
    Run the wat scanner on a FileUpload and store the results.

    This task is intended to be run as part of the submission process only.
    When a version is created from a FileUpload, the files are removed. In
    addition, we usually delete old FileUpload entries after 180 days.

    - `results` are the validation results passed in the validation chain. This
       task is a validation task, which is why it must receive the validation
       results as first argument.
    - `upload_pk` is the FileUpload ID.
    """
    return run_scanner(
        results,
        upload_pk,
        scanner=WAT,
        api_url=settings.WAT_API_URL,
        api_key=settings.WAT_API_KEY
    )


@validation_task
def run_yara(results, upload_pk):
    """
    Apply a set of Yara rules on a FileUpload and store the Yara results
    (matches).

    This task is intended to be run as part of the submission process only.
    When a version is created from a FileUpload, the files are removed. In
    addition, we usually delete old FileUpload entries after 180 days.

    - `results` are the validation results passed in the validation chain. This
       task is a validation task, which is why it must receive the validation
       results as first argument.
    - `upload_pk` is the FileUpload ID.
    """
    log.info('Starting yara task for FileUpload %s.', upload_pk)

    if not results['metadata']['is_webextension']:
        log.info('Not running yara for FileUpload %s, it is not a '
                 'webextension.', upload_pk)
        return results

    upload = FileUpload.objects.get(pk=upload_pk)

    try:
        scanner_result = ScannerResult(upload=upload, scanner=YARA)

        with statsd.timer('devhub.yara'):
            rules = yara.compile(filepath=settings.YARA_RULES_FILEPATH)

            zip_file = SafeZip(source=upload.path)
            for zip_info in zip_file.info_list:
                if not zip_info.is_dir():
                    file_content = zip_file.read(zip_info).decode(
                        errors='ignore'
                    )
                    for match in rules.match(data=file_content):
                        # Add the filename to the meta dict.
                        meta = {**match.meta, 'filename': zip_info.filename}
                        scanner_result.add_match(
                            rule=match.rule,
                            tags=match.tags,
                            meta=meta
                        )
            zip_file.close()

        scanner_result.save()

        if scanner_result.has_matches:
            statsd.incr('devhub.yara.has_matches')

        statsd.incr('devhub.yara.success')
        log.info('Ending scanner "yara" task for FileUpload %s.', upload_pk)
    except Exception:
        statsd.incr('devhub.yara.failure')
        # We log the exception but we do not raise to avoid perturbing the
        # submission flow.
        log.exception('Error in scanner "yara" task for FileUpload %s.',
                      upload_pk)

    return results
