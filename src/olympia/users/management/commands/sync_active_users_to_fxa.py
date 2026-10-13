from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F

from google.cloud import bigquery

import olympia.core.logger
from olympia.core.bigquery import create_client
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.users')


class Command(BaseCommand):
    help = 'Updates FxA bigquery table with a list of all "active" AMO users'

    def handle(self, *args, **options):
        fxa_ids = UserProfile.objects.active().values(uid=F('fxa_id'))
        table_id = settings.FXA_ACTIVES_BIGQUERY_TABLE
        client = create_client()

        log.info(f'Adding {fxa_ids.count()} AMO users to FxAs active table')

        job = client.load_table_from_json(
            fxa_ids,
            table_id,
            job_config=bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            ),
        )
        job.result()
        log.info(f'Added {job.output_rows} rows to FxAs active table')
