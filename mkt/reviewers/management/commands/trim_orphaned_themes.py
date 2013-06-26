import logging

from django.core.management.base import BaseCommand

from addons.models import Addon
from editors.models import RereviewQueueTheme


log = logging.getLogger('z.mkt.reviewers')


class Command(BaseCommand):
    help = 'Deletes reuploaded theme queue objects that do not have Addons.'

    def handle(self, *args, **options):
        for rqt in RereviewQueueTheme.objects.all():
            try:
                rqt.theme.addon
            except Addon.DoesNotExist:
                log.error(
                    'Theme %s is orphaned and does not have an associated '
                    'add-on object.' % rqt.theme.id)
                rqt.delete()
