import os
from datetime import datetime, timedelta

import requests
import yara

from django.conf import settings
from django_statsd.clients import statsd

import olympia.core.logger

from olympia.constants.scanners import (
    ACTIONS,
    CUSTOMS,
    DELAY_AUTO_APPROVAL,
    DELAY_AUTO_APPROVAL_INDEFINITELY,
    FLAG_FOR_HUMAN_REVIEW,
    NO_ACTION,
    SCANNERS,
    WAT,
    YARA,
)
from olympia.addons.models import AddonReviewerFlags
from olympia.devhub.tasks import validation_task
from olympia.files.models import FileUpload
from olympia.files.utils import SafeZip

from .models import ScannerResult, ScannerRule

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
            raise ValueError('File "{}" does not exist.'.format(upload.path))

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
        api_key=settings.CUSTOMS_API_KEY,
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
        api_key=settings.WAT_API_KEY,
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
                        scanner_result.add_yara_result(
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


def _no_action(version):
    """Do nothing."""
    pass


def _flag_for_human_review(version):
    """Flag the version for human review."""
    version.update(needs_human_review=True)


def _delay_auto_approval(version):
    """Delay auto-approval for the whole add-on for 24 hours."""
    # Always flag for human review.
    _flag_for_human_review(version)
    in_twenty_four_hours = datetime.now() + timedelta(hours=24)
    AddonReviewerFlags.objects.update_or_create(
        addon=version.addon,
        defaults={'auto_approval_delayed_until': in_twenty_four_hours})


def _delay_auto_approval_indefinitely(version):
    """Delay auto-approval for the whole add-on indefinitely."""
    # Always flag for human review.
    _flag_for_human_review(version)
    AddonReviewerFlags.objects.update_or_create(
        addon=version.addon,
        defaults={'auto_approval_delayed_until': datetime.max})


def run_action(version):
    """This function tries to find an action to execute for a given version,
    based on the scanner results and associated rules.

    It is not run as a Celery task but as a simple function, in the
    auto_approve CRON."""
    log.info('Checking rules and actions for version %s.', version.pk)

    rule = (
        ScannerRule.objects.filter(
            scannerresult__version=version, is_active=True
        )
        .order_by(
            # The `-` sign means descending order.
            '-action'
        )
        .first()
    )

    if not rule:
        log.info('No action to execute for version %s.', version.pk)
        return

    action_id = rule.action
    action_name = ACTIONS.get(action_id, None)

    if not action_name:
        raise Exception("invalid action %s" % action_id)

    ACTION_FUNCTIONS = {
        NO_ACTION: _no_action,
        FLAG_FOR_HUMAN_REVIEW: _flag_for_human_review,
        DELAY_AUTO_APPROVAL: _delay_auto_approval,
        DELAY_AUTO_APPROVAL_INDEFINITELY: _delay_auto_approval_indefinitely,
    }

    action_function = ACTION_FUNCTIONS.get(action_id, None)

    if not action_function:
        raise Exception("no implementation for action %s" % action_id)

    # We have a valid action to execute, so let's do it!
    log.info('Starting action "%s" for version %s.', action_name, version.pk)
    action_function(version)
    log.info('Ending action "%s" for version %s.', action_name, version.pk)
