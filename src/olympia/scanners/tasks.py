import itertools
import json
import os
import uuid
from collections import defaultdict

from django.conf import settings
from django.db.models import F

import regex
import requests
import waffle
import yara
from django_statsd.clients import statsd
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util import Retry

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import create_chunked_tasks_signatures, task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import (
    attach_trans_dict,
    generate_lowercase_homoglyphs_variants_for_string,
    normalize_string_for_name_checks,
)
from olympia.constants.scanners import (
    ABORTED,
    ABORTING,
    COMPLETED,
    CUSTOMS,
    NARC,
    RUNNING,
    SCANNERS,
    WEBHOOK,
    WEBHOOK_DURING_VALIDATION,
    YARA,
)
from olympia.devhub.tasks import validation_task
from olympia.files.models import FileManifest, FileUpload
from olympia.files.utils import SafeZip
from olympia.versions.models import Version

from .models import (
    ImproperScannerQueryRuleStateError,
    ScannerQueryResult,
    ScannerQueryRule,
    ScannerResult,
    ScannerRule,
    ScannerWebhookEvent,
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


@validation_task
def call_webhooks_during_validation(results, upload_pk):
    log.info('Calling webhooks for FileUpload %s.', upload_pk)
    upload = FileUpload.objects.get(pk=upload_pk)

    try:
        if not os.path.exists(upload.file_path):
            raise ValueError(f'FileUpload "{upload.file_path}" does not exist.')

        call_webhooks(
            event_name=WEBHOOK_DURING_VALIDATION,
            payload={'download_url': upload.get_authenticated_download_url()},
            upload=upload,
        )

        log.info('All webhooks have been called for FileUpload %s.', upload_pk)
    except Exception as exc:
        log.exception('Error while calling webhooks for FileUpload %s.', upload_pk)
        if not waffle.switch_is_active('ignore-exceptions-in-scanner-tasks'):
            raise exc

    return results


def call_webhooks(event_name, payload, upload=None, version=None):
    for event in ScannerWebhookEvent.objects.filter(
        event=event_name, webhook__is_active=True
    ).all():
        log.info('Calling webhook "%s".', event.webhook.name)

        try:
            data = _call_webhook(webhook=event.webhook, payload=payload)

            ScannerResult.objects.create(
                scanner=WEBHOOK,
                webhook_event=event,
                upload=upload,
                version=version,
                results=data,
            )
        except Exception as exc:
            log.exception('Error while calling webhook "%s".', event.webhook.name)
            raise exc


def _call_webhook(webhook, payload):
    with requests.Session() as http:
        adapter = make_adapter_with_retry()
        http.mount('http://', adapter)
        http.mount('https://', adapter)

        response = http.post(
            url=webhook.url,
            json=payload,
            timeout=settings.SCANNER_TIMEOUT,
            headers={'Authorization': f'Bearer {webhook.api_key}'},
        )
    try:
        data = response.json()
    except ValueError as exc:
        # Log the response body when JSON decoding has failed.
        raise ValueError(response.text) from exc

    if response.status_code != 200 or 'error' in data:
        raise ValueError(data)

    return data


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
            url=api_url,
            json=json_payload,
            timeout=settings.SCANNER_TIMEOUT,
            headers={'Authorization': f'Bearer {api_key}'},
        )

    try:
        data = response.json()
    except ValueError as exc:
        # Log the response body when JSON decoding has failed.
        raise ValueError(response.text) from exc

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


@task
@use_primary_db
def run_narc_on_version(version_pk, *, run_action_on_match=True):
    log.info('Starting narc task for Version %s.', version_pk)
    try:
        version = (
            Version.unfiltered.all()
            .no_transforms()
            .select_related('file__file_manifest')
            .get(pk=version_pk)
        )
        scanner_result, initial_run = ScannerResult.objects.get_or_create(
            scanner=NARC, version=version
        )
        with statsd.timer('devhub.narc'):
            scanner_result, has_new_matches = _run_narc(
                version=version, scanner_result=scanner_result
            )
        scanner_result.save()

        if initial_run:
            statsd_suffix = ''
        else:
            statsd_suffix = '.rerun'
        if scanner_result.has_matches:
            statsd.incr(f'devhub.narc{statsd_suffix}.has_matches')
        for scanner_rule in scanner_result.matched_rules.all():
            statsd.incr(f'devhub.narc{statsd_suffix}.rule.{scanner_rule.id}.match')
        if not initial_run and has_new_matches:
            statsd.incr(f'devhub.narc{statsd_suffix}.results_differ')

        if run_action_on_match and has_new_matches:
            ScannerResult.run_action(version)
    except Exception as exc:
        statsd.incr('devhub.narc.failure')
        log.exception(
            'Error in scanner "narc" task for Version %s.', version_pk, exc_info=True
        )
        # Not part of the submission process, so we can always raise.
        raise exc
    else:
        statsd.incr('devhub.narc.success')
    log.info('Ending scanner "narc" task for Version %s.', version_pk)


def _run_narc(*, scanner_result, version, rules=None):
    if not rules:
        rules = ScannerRule.objects.filter(
            scanner=NARC, is_active=True, definition__isnull=False
        ).exclude(definition='')
    results = (
        # Convert existing results to a list of strings to allow results to be
        # hashed to avoid adding duplicates when re-scanning. See result.add()
        # call below and the conversion back at the end before saving as well.
        {json.dumps(result, sort_keys=True) for result in scanner_result.results}
    )
    values_from_db = {}
    values_from_xpi = {}
    values_from_authors = []
    addon = version.addon
    attach_trans_dict(Addon, [addon], field_names=['name'])
    values_from_db = dict(addon.translations[addon.name_id])
    values_from_authors = list(
        addon.authors.all()
        .exclude(display_name=None)
        .values_list('display_name', flat=True)
    )

    # Because we're running on a Version, not a FileUpload, we should already
    # have a FileManifest, so we don't even need to parse the XPI to grab the
    # name.
    try:
        manifest_data = version.file.file_manifest.manifest_data
        data = {
            'name': manifest_data.get('name'),
            'default_locale': manifest_data.get('default_locale'),
        }
    except FileManifest.DoesNotExist:
        # Something else should stop us if the FileManifest is absent, NARC
        # shouldn't fail for that. This means validation was forced by an admin
        # or something similar.
        data = {}
    # Find all translations from the XPI if necessary.
    values_from_xpi = Addon.resolve_webext_translations(
        data, version.file.file, fields=('name',)
    ).get('name', {})
    # If we didn't get a dict, we returned early without bothering to open the
    # XPI because the name wasn't translated in the manifest. We still build
    # a dict for ease of use later.
    if values_from_xpi is None or isinstance(values_from_xpi, str):
        values_from_xpi = {None: values_from_xpi or ''}

    # Gather all values into a dict to avoid repeating the same costly search
    # on duplicate values.
    values = defaultdict(list)
    for source, (locale, value) in itertools.chain(
        zip(itertools.repeat('xpi'), values_from_xpi.items()),
        zip(itertools.repeat('db_addon'), values_from_db.items()),
        zip(
            itertools.repeat('author'),
            zip(itertools.repeat(None), sorted(values_from_authors)),
        ),
    ):
        values[value].append({'source': source, 'locale': locale})

    # Run each rule on the values we've accumulated.
    for rule in rules:
        # We're using `regex`, which is faster/more powerful than the default
        # `re` module.
        definition = regex.compile(str(rule.definition), regex.I | regex.E)
        for value, sources in values.items():
            value = str(value)
            variants = [(value, None)]
            if (normalized_value := normalize_string_for_name_checks(value)) != value:
                variants.append((normalized_value, 'normalized'))
            homoglyph_variants = set(
                generate_lowercase_homoglyphs_variants_for_string(normalized_value)
            )
            if homoglyph_variants:
                variants.extend(
                    (homoglyph_variant, 'homoglyph')
                    for homoglyph_variant in homoglyph_variants
                    if homoglyph_variant != value.lower()
                    and homoglyph_variant != normalized_value.lower()
                )

            for variant, variant_type in variants:
                if match := definition.search(variant):
                    span = tuple(match.span())
                    for source_info in sources:
                        result = {
                            'rule': rule.name,
                            'meta': {
                                'locale': source_info['locale'],
                                'source': source_info['source'],
                                'pattern': rule.definition,
                                'string': variant,
                                'span': span,
                            },
                        }
                        if variant_type is not None:
                            result['meta']['variant'] = variant_type
                            result['meta']['original_string'] = value
                        results.add(json.dumps(result, sort_keys=True))

    has_new_matches = False
    new_results = [json.loads(result) for result in sorted(results)]
    if new_results != scanner_result.results:
        # Either we're scanning this version for the first time, or it's a new
        # run following some change, but in any case we found new results. We
        # might need to run ScannerResult.run_action() as a result, see below.
        has_new_matches = True
    scanner_result.results = new_results
    return scanner_result, has_new_matches


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
def mark_scanner_query_rule_as_completed_or_aborted(query_rule_pk):
    """
    Mark a ScannerQueryRule as completed/aborted.
    """
    rule = ScannerQueryRule.objects.get(pk=query_rule_pk)
    try:
        if rule.state == RUNNING:
            log.info('Marking Scanner Query Rule %s as completed', rule.pk)
            rule.change_state_to(COMPLETED)
        elif rule.state == ABORTING:
            log.info('Marking Scanner Query Rule %s as aborted', rule.pk)
            rule.change_state_to(ABORTED)
    except ImproperScannerQueryRuleStateError:
        log.error(
            'Not marking rule as completed or aborted for rule %s in '
            'mark_scanner_query_rule_as_completed_or_aborted, its state is '
            '%s',
            rule.pk,
            rule.get_state_display(),
        )


@task
def run_scanner_query_rule(query_rule_pk):
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
            'Not proceeding with run_scanner_query_rule on rule %s because '
            'its state is %s',
            rule.pk,
            rule.get_state_display(),
        )
        return
    log.info('Fetching versions for run_scanner_query_rule on rule %s', rule.pk)
    # Build a huge list of all pks we're going to run the tasks on.
    qs = Version.unfiltered.filter(
        addon__type=amo.ADDON_EXTENSION, file__isnull=False
    ).exclude(file__file='')
    if not rule.run_on_disabled_addons:
        qs = qs.exclude(addon__status=amo.STATUS_DISABLED)
    if rule.run_on_specific_channel:
        qs = qs.filter(channel=rule.run_on_specific_channel)
    if rule.run_on_current_version_only:
        qs = qs.filter(pk=F('addon___current_version'))
    if rule.exclude_promoted_addons:
        qs = qs.exclude(addon__promotedaddon__isnull=False)
    qs = qs.values_list('id', flat=True).order_by('-pk')
    # Build the workflow using a group of tasks dealing with 250 files at a
    # time, chained to a task that marks the query as completed.
    chunk_size = 250
    chunked_tasks = create_chunked_tasks_signatures(
        run_scanner_query_rule_on_versions_chunk,
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
    workflow = chunked_tasks | mark_scanner_query_rule_as_completed_or_aborted.si(
        query_rule_pk
    )
    log.info(
        'Running workflow of %s tasks for run_scanner_query_rule on rule %s',
        len(chunked_tasks),
        rule.pk,
    )
    # Fire it up.
    workflow.apply_async()


@task(ignore_result=False)  # We want the results to track completion rate.
def run_scanner_query_rule_on_versions_chunk(version_pks, query_rule_pk):
    """
    Task to run a specific ScannerQueryRule on a list of versions.

    Needs the rule to be a the RUNNING state, otherwise does nothing.
    """
    log.info(
        'Running Scanner Query Rule %s on versions %s-%s.',
        query_rule_pk,
        version_pks[0],
        version_pks[-1],
    )
    # Like run_scanner_query_rule() we don't want to decorate this function to
    # force it to run on the primary, we want to leverage the replicas as much
    # as possible while avoiding raising if replication lag causes the rule not
    # to exist yet when the task is triggered.
    rule = ScannerQueryRule.objects.all().get_with_primary_fallback(pk=query_rule_pk)
    if rule.state != RUNNING:
        log.info(
            'Not doing anything for Scanner Query Rule %s on versions %s-%s '
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
            _run_scanner_query_rule_on_version(version, rule)
        except Exception:
            log.exception(
                'Error in run_scanner_query_rule_on_version task for Version %s.',
                version_pk,
            )


def _run_scanner_query_rule_on_version(version, rule):
    """
    Run a specific ScannerQueryRule on a Version.
    """
    file_ = version.file
    scanner_result = ScannerQueryResult(version=version, scanner=rule.scanner)
    if rule.scanner == YARA:
        _run_yara_for_path(scanner_result, file_.file.path, definition=rule.definition)
    elif rule.scanner == NARC:
        _run_narc(scanner_result=scanner_result, version=version, rules=[rule])
    else:
        raise NotImplementedError

    # Unlike ScannerResult, we only want to save ScannerQueryResult if there is
    # a match, there would be too many things to save otherwise and we don't
    # really care about non-matches.
    if scanner_result.results:
        scanner_result.was_blocked = version.is_blocked
        scanner_result.was_promoted = version.addon.is_promoted
        scanner_result.save()

    return scanner_result
