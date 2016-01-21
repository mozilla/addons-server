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


def filter_messages(messages):
    """
    Only return messages that are the right type and under the limit.
    """
    error_count = 0
    result = []
    for message in messages:
        if message['type'] in settings.GITHUB_COMMENT_TYPES:
            error_count += 1
            if error_count > settings.GITHUB_COMMENTS_PER_VALIDATION:
                break
            result.append(message)

    log.info('Filtered to {} comments on pull requests'.format(len(result)))
    return result


@task
def process_results(upload_pk, callbacks):
    log.info('Processing validation results for: {}'.format(upload_pk))
    upload = FileUpload.objects.get(pk=upload_pk)
    validation = json.loads(upload.validation) if upload.validation else {}
    github = GithubCallback(callbacks)
    url = absolutify(
        reverse('devhub.standalone_upload_detail', args=[upload.pk]))

    if not validation:
        log.error('Validation not written: {}'.format(upload_pk))
        github.failure()
        return

    if validation.get('success'):
        log.info('Notifying success for: {}'.format(upload_pk))
        github.success(url)
        return

    log.info('Notifying errors for: {}'.format(upload_pk))
    for message in filter_messages(validation.get('messages', [])):
        github.comment({
            'body': ' '.join(message['description']),
            # Github requires that the position number is at least 1
            # we'll use this when the validator returns no position.
            'position': message['line'] or 1,
            'path': message['file'],
            'commit_id': github.data['sha'],
        })

    github.error(url)
