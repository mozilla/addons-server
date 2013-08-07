from django.core.management.base import BaseCommand, CommandError

from celery.task.sets import TaskSet

import amo
from amo.utils import chunked
from mkt.constants.regions import REGIONS_CHOICES_SLUG
from mkt.developers.tasks import new_payments_region_email
from mkt.webapps.models import Webapp


class Command(BaseCommand):
    help = 'Email developers of public paid apps about a newly added region.'
    args = '<region_slug>'

    def handle(self, *args, **options):
        if len(args) != 1:
            regions = ', '.join(dict(REGIONS_CHOICES_SLUG[1:]).keys())
            raise CommandError(('You must enter a single region slug. '
                                'Available choices: %s' % regions))
        region_slug = args[0]
        ids = (Webapp.objects.filter(premium_type__in=amo.ADDON_HAS_PAYMENTS)
                             .exclude(status__in=amo.WEBAPPS_EXCLUDED_STATUSES)
                             .values_list('id', flat=True))
        ts = [new_payments_region_email.subtask(args=[chunk, region_slug])
              for chunk in chunked(ids, 100)]
        TaskSet(ts).apply_async()
