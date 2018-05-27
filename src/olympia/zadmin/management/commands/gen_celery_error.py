from django.core.management.base import BaseCommand

from olympia.zadmin.tasks import celery_error


class Command(BaseCommand):
    help = 'Generates an exception from a celery task for testing'

    def handle(self, *args, **options):
        celery_error.delay()
        print('A RuntimeError exception was raised from a celery task. '
              'Check the logs!')
