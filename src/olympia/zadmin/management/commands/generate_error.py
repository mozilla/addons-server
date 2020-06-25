from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.zadmin.tasks import celery_error


log = olympia.core.logger.getLogger('z')


class Command(BaseCommand):
    help = (
        'Generates an exception for testing. From a celery task with --celery')

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--celery',
            default=False,
            action='store_true',
            help='Raise the error in a celery task')

    def handle(self, *args, **options):
        if options.get('celery'):
            celery_error.delay()
            print('A RuntimeError exception was raised from a celery task. '
                  'Check the logs!')
        else:
            try:
                print('Raising an exception that will be caught')
                raise RuntimeError(
                    'This is an exception from a management command')
            except Exception as exception:
                print('Logging the exception')
                log.exception(
                    'Capturing exception as a log', exc_info=exception)
                print('And re-raising it')
                raise exception
