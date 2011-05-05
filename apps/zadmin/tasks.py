from datetime import datetime
import logging
import os
import sys
import traceback

from django.conf import settings
from django.db import connection
from django.template import Context, Template

from celeryutils import task

import amo
from amo.decorators import write
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import send_mail
from devhub.tasks import run_validator
from files.models import File
from versions.models import Version
from zadmin.models import ValidationResult, ValidationJob

log = logging.getLogger('z.task')


def tally_job_results(job_id, **kw):
    sql = """select sum(1),
                    sum(case when completed IS NOT NULL then 1 else 0 end)
             from validation_result
             where validation_job_id=%s"""
    cursor = connection.cursor()
    cursor.execute(sql, [job_id])
    total, completed = cursor.fetchone()
    if completed == total:
        ValidationJob.objects.get(pk=job_id).update(completed=datetime.now())


@task(rate_limit='2/s')
@write
def bulk_validate_file(result_id, **kw):
    res = ValidationResult.objects.get(pk=result_id)
    task_error = None
    validation = None
    try:
        file_base = os.path.basename(res.file.file_path)
        log.info('[1@None] Validating file %s (%s) for result_id %s'
                 % (res.file, file_base, res.id))
        target = res.validation_job.target_version
        ver = {target.application.guid: [target.version]}
        validation = run_validator(res.file.file_path, for_appversions=ver)
    except:
        task_error = sys.exc_info()
        log.error(task_error[1])

    res.completed = datetime.now()
    if task_error:
        res.task_error = ''.join(traceback.format_exception(*task_error))
    else:
        res.apply_validation(validation)
        log.info('[1@None] File %s (%s) errors=%s'
                 % (res.file, file_base, res.errors))
    res.save()
    tally_job_results(res.validation_job.id)

    if task_error:
        etype, val, tb = task_error
        raise etype, val, tb


@task
@write
def set_max_versions(version_pks, job_pk, **kw):
    log.info('[%s@None] Updating max version for job %s.'
             % (len(version_pks), job_pk))
    job = ValidationJob.objects.get(pk=job_pk)
    for version in Version.objects.filter(pk__in=version_pks):
        file_pks = version.files.values_list('pk', flat=True)
        errors = (ValidationResult.objects.filter(validation_job=job,
                                                  file__pk__in=file_pks)
                                          .values_list('errors', flat=True))
        if any(errors):
            log.info('Version %s for addon %s not updated, '
                     'one of the files did not pass validation'
                     % (version.pk, version.addon.pk))
            continue

        for app in version.apps.filter(application=
                                       job.curr_max_version.application):
            if (app.max.version == job.curr_max_version.version and
                job.target_version.version != app.max.version):
                log.info('Updating version %s for addon %s from version %s '
                         'to version %s'
                         % (version.pk, version.addon.pk,
                            job.curr_max_version.version,
                            job.target_version.version))
                app.max = job.target_version
                app.save()
                amo.log(amo.LOG.BULK_VALIDATION_UPDATED,
                        version.addon, version,
                        details={'version': version.version,
                                 'target': job.target_version.version})

            else:
                log.info('Version %s for addon %s not updated, '
                         'current max version is %s not %s'
                         % (version.pk, version.addon.pk,
                            app.max.version, job.curr_max_version.version))


@task
@write
def notify_failed(file_pks, job_pk, data, **kw):
    log.info('[%s@None] Notifying failed for job %s.'
             % (len(file_pks), job_pk))
    job = ValidationJob.objects.get(pk=job_pk)
    template = Template(data['text'])

    for obj in File.objects.filter(pk__in=file_pks):
        version = obj.version
        addon = version.addon
        context = Context({
            'ADDON_NAME': addon.name,
            # TODO(andym): link when we have results page bug 649863 maybe?
            'RESULTS_LINK': '',
            'COMPAT_LINK': (absolutify(reverse('devhub.versions.edit',
                                               args=[addon.pk, version.pk]))),
        })

        for author in addon.authors.all():
            log.info(u'Emailing %s for addon %s, file %s about '
                     'error from bulk validation job %s'
                     % (author.email, addon.pk, obj.pk, job_pk))
            send_mail(u'Mozilla Add-ons: %s' % addon.name,
                      template.render(context),
                      from_email=settings.DEFAULT_FROM_EMAIL,
                      recipient_list=[author.email])

        amo.log(amo.LOG.BULK_VALIDATION_EMAILED,
                addon, version,
                details={'version': version.version,
                         'file': obj.filename,
                         'target': job.target_version.version})
