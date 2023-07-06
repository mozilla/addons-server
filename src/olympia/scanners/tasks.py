import os
import uuid

from django.conf import settings

import requests
import waffle
import yara
from django_statsd.clients import statsd
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util import Retry

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
    YARA,
)
from olympia.devhub.tasks import validation_task
from olympia.files.models import FileUpload
from olympia.files.utils import SafeZip
from olympia.versions.models import Version

from .models import (
    ImproperScannerQueryRuleStateError,
    ScannerQueryResult,
    ScannerQueryRule,
    ScannerResult,
    ScannerRule,
)


log = olympia.core.logger.getLogger('z.scanners.task')


def make_adapter_with_retry():
    adapter = HTTPAdapter(
        max_retries=Retry(
            total=1,
            allowed_methods=['POST'],
            status_forcelist=[500, 502, 503, 504],
        )
    )
    return adapter


def run_scanner(results, upload_pk, scanner, api_url, api_key):
    """
    Run a scanner on a FileUpload via RPC and store the results.

    - `results` are the validation results passed in the validation chain. This
       task is a validation task, which is why it must receive the validation
       results as first argument.
    - `upload_pk` is the FileUpload ID.
    """
    scanner_name = SCANNERS.get(scanner)
    log.info('Starting scanner "%s" task for FileUpload %s.', scanner_name, upload_pk)

    upload = FileUpload.objects.get(pk=upload_pk)

    try:
        if not os.path.exists(upload.file_path):
            raise ValueError(f'FileUpload "{upload.file_path}" does not exist.')

        scanner_result = ScannerResult(upload=upload, scanner=scanner)

        with statsd.timer(f'devhub.{scanner_name}'):
            _run_scanner_for_url(
                scanner_result,
                upload.get_authenticated_download_url(),
                scanner,
                api_url,
                api_key,
            )

        scanner_result.save()

        if scanner_result.has_matches:
            statsd.incr(f'devhub.{scanner_name}.has_matches')
            for scanner_rule in scanner_result.matched_rules.all():
                statsd.incr(f'devhub.{scanner_name}.rule.{scanner_rule.id}.match')

        statsd.incr(f'devhub.{scanner_name}.success')
        log.info('Ending scanner "%s" task for FileUpload %s.', scanner_name, upload_pk)
    except Exception as exc:
        statsd.incr(f'devhub.{scanner_name}.failure')
        log.exception(
            'Error in scanner "%s" task for FileUpload %s.', scanner_name, upload_pk
        )
        if not waffle.switch_is_active('ignore-exceptions-in-scanner-tasks'):
            raise exc

    return results


def _run_scanner_for_url(scanner_result, url, scanner, api_url, api_key):
    """
    Inner function to run a scanner on a particular URL via RPC and add results
    to the given scanner_result. The caller is responsible for saving the
    scanner_result to the database.
    """
    with requests.Session() as http:
        adapter = make_adapter_with_retry()
        http.mount('http://', adapter)
        http.mount('https://', adapter)

        json_payload = {
            'api_key': api_key,
            'download_url': url,
        }
        response = http.post(
            url=api_url, json=json_payload, timeout=settings.SCANNER_TIMEOUT
        )

    try:
        data = response.json()
    except ValueError:
        # Log the response body when JSON decoding has failed.
        raise ValueError(response.text)

    if response.status_code != 200 or 'error' in data:
        raise ValueError(data)

    scanner_result.results = data


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
    return _run_yara(results, upload_pk)


def _run_yara(results, upload_pk):
    log.info('Starting yara task for FileUpload %s.', upload_pk)

    try:
        upload = FileUpload.objects.get(pk=upload_pk)
        scanner_result = ScannerResult(upload=upload, scanner=YARA)
        _run_yara_for_path(scanner_result, upload.file_path)
        scanner_result.save()

        if scanner_result.has_matches:
            statsd.incr('devhub.yara.has_matches')
            for scanner_rule in scanner_result.matched_rules.all():
                statsd.incr(f'devhub.yara.rule.{scanner_rule.id}.match')

        statsd.incr('devhub.yara.success')
        log.info('Ending scanner "yara" task for FileUpload %s.', upload_pk)
    except Exception as exc:
        statsd.incr('devhub.yara.failure')
        log.exception(
            'Error in scanner "yara" task for FileUpload %s.', upload_pk, exc_info=True
        )
        if not waffle.switch_is_active('ignore-exceptions-in-scanner-tasks'):
            raise exc

    return results


def _run_yara_for_path(scanner_result, path, definition=None):
    """
    Inner function to run yara on a particular path and add results to the
    given scanner_result. The caller is responsible for saving the
    scanner_result to the database.

    Takes an optional definition to run a single arbitrary yara rule, otherwise
    uses all active yara ScannerRules.
    """
    with statsd.timer('devhub.yara'):
        if definition is None:
            # Retrieve then concatenate all the active/valid Yara rules.
            definition = '\n'.join(
                ScannerRule.objects.filter(
                    scanner=YARA, is_active=True, definition__isnull=False
                ).values_list('definition', flat=True)
            )
        # Initialize external variables so that compilation works, we'll
        # override them later when matching.
        externals = ScannerRule.get_yara_externals()
        rules = yara.compile(source=definition, externals=externals)

        zip_file = SafeZip(source=path, ignore_filename_errors=True)
        for zip_info in zip_file.info_list:
            if not zip_info.is_dir():
                file_content = zip_file.read(zip_info)
                filename = zip_info.filename
                # Fill externals variable for this file.
                externals['is_json_file'] = filename.endswith('.json')
                externals['is_manifest_file'] = filename == 'manifest.json'
                externals['is_locale_file'] = filename.startswith(
                    '_locales/'
                ) and filename.endswith('/messages.json')
                for match in rules.match(data=file_content, externals=externals):
                    # Also add the filename to the meta dict in results.
                    meta = {**match.meta, 'filename': filename}
                    scanner_result.add_yara_result(
                        rule=match.rule, tags=match.tags, meta=meta
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
        log.error(
            'Not marking rule as completed or aborted for rule %s in '
            'mark_yara_query_rule_as_completed_or_aborted, its state is '
            '%s',
            rule.pk,
            rule.get_state_display(),
        )


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
        log.error(
            'Not proceeding with run_yara_query_rule on rule %s because '
            'its state is %s',
            rule.pk,
            rule.get_state_display(),
        )
        return
    log.info('Fetching versions for run_yara_query_rule on rule %s', rule.pk)
    # Build a huge list of all pks we're going to run the tasks on.
    qs = Version.unfiltered.filter(
        addon__type=amo.ADDON_EXTENSION, file__isnull=False
    ).exclude(file__file='')
    if not rule.run_on_disabled_addons:
        qs = qs.exclude(addon__status=amo.STATUS_DISABLED)
    qs = qs.values_list('id', flat=True).order_by('-pk')
    # Build the workflow using a group of tasks dealing with 250 files at a
    # time, chained to a task that marks the query as completed.
    chunk_size = 250
    chunked_tasks = create_chunked_tasks_signatures(
        run_yara_query_rule_on_versions_chunk,
        list(qs),
        chunk_size,
        task_args=(query_rule_pk,),
    )
    # Force the group id to be generated for those tasks, and store it in the
    # result backend.
    group_result = chunked_tasks.freeze()
    group_result.save()
    rule.update(
        task_count=len(chunked_tasks), celery_group_result_id=uuid.UUID(group_result.id)
    )
    workflow = chunked_tasks | mark_yara_query_rule_as_completed_or_aborted.si(
        query_rule_pk
    )
    log.info(
        'Running workflow of %s tasks for run_yara_query_rule on rule %s',
        len(chunked_tasks),
        rule.pk,
    )
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
        query_rule_pk,
        version_pks[0],
        version_pks[-1],
    )
    rule = ScannerQueryRule.objects.get(pk=query_rule_pk)
    if rule.state != RUNNING:
        log.info(
            'Not doing anything for Yara Query Rule %s on versions %s-%s '
            'since rule state is %s.',
            query_rule_pk,
            version_pks[0],
            version_pks[-1],
            rule.get_state_display(),
        )
        return
    for version_pk in version_pks:
        try:
            version = (
                Version.unfiltered.all()
                .select_related('addon__addonguid')
                .no_transforms()
                .get(pk=version_pk)
            )
            _run_yara_query_rule_on_version(version, rule)
        except Exception:
            log.exception(
                'Error in run_yara_query_rule_on_version task for Version %s.',
                version_pk,
            )


def _run_yara_query_rule_on_version(version, rule):
    """
    Run a specific ScannerQueryRule on a Version.
    """
    file_ = version.file
    scanner_result = ScannerQueryResult(version=version, scanner=YARA)
    _run_yara_for_path(scanner_result, file_.file.path, definition=rule.definition)
    # Unlike ScannerResult, we only want to save ScannerQueryResult if there is
    # a match, there would be too many things to save otherwise and we don't
    # really care about non-matches.
    if scanner_result.results:
        scanner_result.was_blocked = version.is_blocked
        scanner_result.save()

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
    # In case of a validation error (linter or scanner), we do want to skip
    # this task. This is similar to the behavior of all other tasks decorated
    # with `@validation_task` but, because this task is the callback of a
    # Celery chord, we cannot use this decorator.
    for results in all_results:
        if results['errors'] > 0:
            return results

    # The first task registered in the chord is `forward_linter_results()`:
    results = all_results[0]

    if not waffle.switch_is_active('enable-mad'):
        log.info('Skipping scanner "mad" task, switch is off')
        return results

    request_id = uuid.uuid4().hex
    log.info(
        'Starting scanner "mad" task for FileUpload %s, request_id=%s.',
        upload_pk,
        request_id,
    )

    try:
        # TODO: retrieve all scanner results and pass each result to the API.
        customs_results = ScannerResult.objects.get(
            upload_id=upload_pk, scanner=CUSTOMS
        )

        scanMapKeys = customs_results.results.get('scanMap', {}).keys()
        if len(scanMapKeys) < 2:
            log.info(
                'Not calling scanner "mad" for FileUpload %s, scanMap is too small.',
                upload_pk,
            )
            statsd.incr('devhub.mad.skip')
            return results

        with statsd.timer('devhub.mad'):
            with requests.Session() as http:
                adapter = make_adapter_with_retry()
                http.mount('http://', adapter)
                http.mount('https://', adapter)

                json_payload = {'scanners': {'customs': customs_results.results}}
                response = http.post(
                    url=settings.MAD_API_URL,
                    json=json_payload,
                    timeout=settings.MAD_API_TIMEOUT,
                    headers={'x-request-id': request_id},
                )

        try:
            data = response.json()
        except ValueError:
            # Log the response body when JSON decoding has failed.
            raise ValueError(response.text)

        if response.status_code != 200:
            raise ValueError(data)

        default_score = -1
        ScannerResult.objects.create(
            upload_id=upload_pk,
            scanner=MAD,
            results=data,
            score=data.get('ensemble', default_score),
        )

        # Update the individual scanner results with some info from MAD.
        customs_data = data.get('scanners', {}).get('customs', {})
        customs_score = customs_data.get('score', default_score)
        customs_model_version = customs_data.get('model_version')
        customs_results.update(score=customs_score, model_version=customs_model_version)

        statsd.incr('devhub.mad.success')
        log.info('Ending scanner "mad" task for FileUpload %s.', upload_pk)
    except Exception:
        statsd.incr('devhub.mad.failure')
        # We log the exception but we do not raise to avoid perturbing the
        # submission flow.
        log.exception('Error in scanner "mad" task for FileUpload %s.', upload_pk)

    return results
