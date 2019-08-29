import yara

from django.conf import settings
from django_statsd.clients import statsd

import olympia.core.logger

from olympia.amo.celery import task
from olympia.files.models import FileUpload
from olympia.files.utils import SafeZip

from .models import YaraResult

log = olympia.core.logger.getLogger('z.yara.task')


@task
def run_yara(upload_pk):
    """
    Apply a set of Yara rules on a FileUpload and store the results.

    This task is intended to be run as part of the submission process only.
    When a version is created from a FileUpload, the files are removed. In
    addition, we usually delete old FileUpload entries after 180 days.
    """
    log.info('Starting yara task for FileUpload %s.', upload_pk)
    upload = FileUpload.objects.get(pk=upload_pk)

    if not upload.path.endswith('.xpi'):
        log.info('Not running yara for FileUpload %s, it is not a xpi file.',
                 upload_pk)
        return

    try:
        result = YaraResult()
        result.upload = upload

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
                        result.add_match(
                            rule=match.rule,
                            tags=match.tags,
                            meta=meta
                        )
            zip_file.close()

        result.save()

        log.info('Ending yara task for FileUpload %s.', upload_pk)
    except Exception:
        # We log the exception but we do not raise to avoid perturbing the
        # submission flow.
        log.exception('Error in yara task for FileUpload %s.', upload_pk)
