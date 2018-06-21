import json

import olympia.core.logger

from olympia.amo.celery import task
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.devhub.tasks import validate
from olympia.files.models import FileUpload
from olympia.github.utils import GithubCallback, rezip_file


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
    url = absolutify(
        reverse('devhub.upload_detail', args=[upload.uuid]))

    if not validation:
        log.error('Validation not written: {}'.format(upload_pk))
        github.failure()
        return

    if validation.get('success'):
        log.info('Notifying success for: {}'.format(upload_pk))
        github.success(url)
        return

    log.info('Notifying errors for: {}'.format(upload_pk))
    github.error(url)
