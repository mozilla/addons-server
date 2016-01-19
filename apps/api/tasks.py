import commonware
import json

from django.conf import settings

from amo.celery import task
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from apps.api.github import GithubCallback, rezip_file
from apps.files.models import FileUpload
from apps.devhub.tasks import validate

log = commonware.log.getLogger('z.github')


@task
def process_webhook(upload_pk, callbacks):
    log.info('Processing webhook for: {}'.format(upload_pk))
    upload = FileUpload.objects.get(pk=upload_pk)
    github = GithubCallback(callbacks)
    res = github.get()

    upload.name = '{}-github-webhook.xpi'.format(upload.pk)
    upload.path = rezip_file(res, upload.pk)
    upload.save()

    log.info('Validating: {}'.format(upload_pk))
    validate(
        upload,
        listed=True,
        subtask=process_results.si(upload_pk, callbacks)
    )


@task
def process_results(upload_pk, callbacks):
    log.info('Processing validation results for: {}'.format(upload_pk))
    upload = FileUpload.objects.get(pk=upload_pk)
    validation = json.loads(upload.validation) if upload.validation else {}
    github = GithubCallback(callbacks)

    if not validation:
        log.error('Validation not written: {}'.format(upload_pk))
        github.failure()
        return

    if validation.get('success'):
        log.info('Notifying success for: {}'.format(upload_pk))
        github.success()
        return

    log.info('Notifying errors for: {}'.format(upload_pk))
    error_count = 0
    for message in validation.get('messages', []):
        if message['type'] == 'error':
            if error_count < settings.GITHUB_ERRORS_PER_VALIDATION:
                github.comment({
                    'body': ' '.join(message['description']),
                    # Github requires that the position number is at least 1
                    # we'll use this when the validator returns no position.
                    'position': message['line'] or 1,
                    'path': message['file'],
                    'commit_id': github.data['sha'],
                })
            else:
                log.info('Not sending comment due to github comment limit.')
            error_count += 1

    description = (
        'This add-on did not validate. {} {} found.'
        .format(error_count, 'errors' if error_count > 1 else 'error'))
    if error_count > settings.GITHUB_ERRORS_PER_VALIDATION:
        description += (
            ' Only the first {} errors are reported.'
            .format(settings.GITHUB_ERRORS_PER_VALIDATION)
        )
    github.error(
        description,
        absolutify(
            reverse('devhub.standalone_upload_detail', args=[upload.pk]))
    )
