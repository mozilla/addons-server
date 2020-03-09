import os
import uuid

from django.conf import settings

import requests
import waffle
import yara

from django_statsd.clients import statsd

import olympia.core.logger

from olympia import amo
from olympia.amo.celery import create_chunked_tasks_signatures, task
from olympia.amo.decorators import use_primary_db
from olympia.constants.scanners import (
    ABORTED,
    ABORTING,
    COMPLETED,
    CUSTOMS,
    MAD,
    RUNNING,
    SCANNERS,
    WAT,
    YARA,
)
from olympia.devhub.tasks import validation_task
from olympia.files.models import FileUpload
from olympia.files.utils import SafeZip
from olympia.versions.models import Version

from .models import (
    ImproperScannerQueryRuleStateError, ScannerQueryResult, ScannerQueryRule,
    ScannerResult, ScannerRule)


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

        if scanner_result.has_matches:
            statsd.incr('devhub.{}.has_matches'.format(scanner_name))
            for scanner_rule in scanner_result.matched_rules.all():
                statsd.incr(
                    'devhub.{}.rule.{}.match'.format(
                        scanner_name, scanner_rule.id
                    )
                )

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

    try:
        upload = FileUpload.objects.get(pk=upload_pk)
        scanner_result = ScannerResult(upload=upload, scanner=YARA)
        _run_yara_for_path(scanner_result, upload.path)
        scanner_result.save()

        if scanner_result.has_matches:
            statsd.incr('devhub.yara.has_matches')
            for scanner_rule in scanner_result.matched_rules.all():
                statsd.incr(
                    'devhub.yara.rule.{}.match'.format(scanner_rule.id)
                )

        statsd.incr('devhub.yara.success')
        log.info('Ending scanner "yara" task for FileUpload %s.', upload_pk)
    except Exception:
        statsd.incr('devhub.yara.failure')
        # We log the exception but we do not raise to avoid perturbing the
        # submission flow.
        log.exception('Error in scanner "yara" task for FileUpload %s.',
                      upload_pk)

    return results


def _run_yara_for_path(scanner_result, path, definition=None):
    with statsd.timer('devhub.yara'):
        if definition is None:
            # Retrieve then concatenate all the active/valid Yara rules.
            definition = '\n'.join(
                ScannerRule.objects.filter(
                    scanner=YARA, is_active=True, definition__isnull=False
                ).values_list('definition', flat=True)
            )

        rules = yara.compile(source=definition)

        zip_file = SafeZip(source=path)
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


@task
@use_primary_db
def mark_yara_query_rule_as_completed_or_aborted(query_rule_pk):
    """
    Mark a ScannerQueryRule as completed/aborted.
    """
    rule = ScannerQueryRule.objects.get(pk=query_rule_pk)
    try:
        if rule.state == RUNNING:
            log.info('Marking Yara Query Rule %s as completed', rule.pk)
            rule.change_state_to(COMPLETED)
        elif rule.state == ABORTING:
            log.info('Marking Yara Query Rule %s as aborted', rule.pk)
            rule.change_state_to(ABORTED)
    except ImproperScannerQueryRuleStateError:
        log.error('Not marking rule as completed or aborted for rule %s in '
                  'mark_yara_query_rule_as_completed_or_aborted, its state is '
                  '%s', rule.pk, rule.get_state_display())


@task
def run_yara_query_rule(query_rule_pk):
    """
    Run a specific ScannerQueryRule on multiple Versions.

    Needs the rule to be a the SCHEDULED state, otherwise does nothing.
    """
    # We're not forcing this task to happen on primary db to let the replicas
    # handle the Version query below, but we want to fetch the rule using the
    # primary db in all cases.
    rule = ScannerQueryRule.objects.using('default').get(pk=query_rule_pk)
    try:
        rule.change_state_to(RUNNING)
    except ImproperScannerQueryRuleStateError:
        log.error('Not proceeding with run_yara_query_rule on rule %s because '
                  'its state is %s', rule.pk, rule.get_state_display())
        return
    log.info('Fetching versions for run_yara_query_rule on rule %s', rule.pk)
    # Build a huge list of all pks we're going to run the tasks on.
    qs = Version.unfiltered.filter(
        addon__type=amo.ADDON_EXTENSION, files__is_webextension=True,
    )
    if not rule.run_on_disabled_addons:
        qs = qs.exclude(addon__status=amo.STATUS_DISABLED)
    qs = qs.values_list('id', flat=True).order_by('pk')
    # Build the workflow using a group of tasks dealing with 250 files at a
    # time, chained to a task that marks the query as completed.
    chunk_size = 250
    chunked_tasks = create_chunked_tasks_signatures(
        run_yara_query_rule_on_versions_chunk, list(qs), chunk_size,
        task_args=(query_rule_pk,))
    # Force the group id to be generated for those tasks, and store it in the
    # result backend.
    group_result = chunked_tasks.freeze()
    group_result.save()
    rule.update(
        task_count=len(chunked_tasks),
        celery_group_result_id=uuid.UUID(group_result.id)
    )
    workflow = (
        chunked_tasks |
        mark_yara_query_rule_as_completed_or_aborted.si(query_rule_pk)
    )
    log.info('Running workflow of %s tasks for run_yara_query_rule on rule %s',
             len(chunked_tasks), rule.pk)
    # Fire it up.
    workflow.apply_async()


@task(ignore_result=False)  # We want the results to track completion rate.
@use_primary_db
def run_yara_query_rule_on_versions_chunk(version_pks, query_rule_pk):
    """
    Task to run a specific ScannerQueryRule on a list of versions.

    Needs the rule to be a the RUNNING state, otherwise does nothing.
    """
    log.info(
        'Running Yara Query Rule %s on versions %s-%s.',
        query_rule_pk, version_pks[0], version_pks[-1])
    rule = ScannerQueryRule.objects.get(pk=query_rule_pk)
    if rule.state != RUNNING:
        log.info(
            'Not doing anything for Yara Query Rule %s on versions %s-%s '
            'since rule state is %s.', query_rule_pk, version_pks[0],
            version_pks[-1], rule.get_state_display())
        return
    for version_pk in version_pks:
        try:
            version = Version.unfiltered.all().no_transforms().get(
                pk=version_pk)
            _run_yara_query_rule_on_version(version, rule)
        except Exception:
            log.exception(
                'Error in run_yara_query_rule_on_version task for Version %s.',
                version_pk)


def _run_yara_query_rule_on_version(version, rule):
    """
    Run a specific ScannerQueryRule on a Version.
    """
    file_ = version.all_files[0]
    scanner_result = ScannerQueryResult(version=version, scanner=YARA)
    try:
        _run_yara_for_path(
            scanner_result, file_.current_file_path,
            definition=rule.definition)
    except FileNotFoundError:
        # Fallback in case the file was disabled/re-enabled and not yet moved,
        # we try the other possible path. This shouldn't happen too often.
        tried_path = file_.current_file_path
        fallback_path = (
            file_.file_path if tried_path == file_.guarded_file_path
            else file_.guarded_file_path
        )
        _run_yara_for_path(
            scanner_result, fallback_path, definition=rule.definition)
    # Unlike ScannerResult, we only want to save ScannerQueryResult if there is
    # a match, there would be too many things to save otherwise and we don't
    # really care about non-matches.
    if scanner_result.results:
        scanner_result.save()
    # FIXME: run_action ?
    return scanner_result


@task
@use_primary_db
def call_mad_api(all_results, upload_pk):
    """
    Call the machine learning API (mad-server) for a given FileUpload.

    This task is the callback of the Celery chord in the validation chain. It
    receives all the results returned by all the tasks in this chord.

    - `all_results` are the results returned by all the tasks in the chord.
    - `upload_pk` is the FileUpload ID.
    """
    # This task is the callback of a Celery chord and receives all the results
    # returned by all the tasks in this chord. The first task registered in the
    # chord is `forward_linter_results()`:
    results = all_results[0]

    if not waffle.switch_is_active('enable-mad'):
        log.debug('Skipping scanner "mad" task, switch is off')
        return results

    log.info('Starting scanner "mad" task for FileUpload %s.', upload_pk)

    if not results['metadata']['is_webextension']:
        log.info(
            'Not calling scanner "mad" for FileUpload %s, it is not '
            'a webextension.',
            upload_pk,
        )
        return results

    try:
        # TODO: retrieve all scanner results and pass each result to the API.
        customs_results = ScannerResult.objects.get(
            upload_id=upload_pk, scanner=CUSTOMS
        )

        with statsd.timer('devhub.mad'):
            json_payload = {'customs': customs_results.results}
            response = requests.post(
                url=settings.MAD_API_URL,
                json=json_payload,
                timeout=settings.MAD_API_TIMEOUT,
            )

        try:
            data = response.json()
        except ValueError:
            # Log the response body when JSON decoding has failed.
            raise ValueError(response.text)

        if response.status_code != 200:
            raise ValueError(data)

        ScannerResult.objects.create(
            upload_id=upload_pk, scanner=MAD, results=data
        )

        statsd.incr('devhub.mad.success')
        log.info('Ending scanner "mad" task for FileUpload %s.', upload_pk)
    except Exception:
        statsd.incr('devhub.mad.failure')
        # We log the exception but we do not raise to avoid perturbing the
        # submission flow.
        log.exception(
            'Error in scanner "mad" task for FileUpload %s.', upload_pk
        )

    return results
