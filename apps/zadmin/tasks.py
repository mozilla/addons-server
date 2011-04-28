from datetime import datetime
import logging
import os
import sys
import traceback

from django.db import connection

from celeryutils import task

from amo.decorators import write
from devhub.tasks import _validator
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


@task
@write
def bulk_validate_file(result_id, **kw):
    res = ValidationResult.objects.get(pk=result_id)
    file_base = os.path.basename(res.file.file_path)
    log.info('[1@None] Validating file %s (%s) for result_id %s'
             % (res.file, file_base, res.id))
    task_error = None
    validation = None
    try:
        # TODO(Kumar) when supported, add for_appversions={'{guid}': [1,2]}
        validation = _validator(res.file.file_path)
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
