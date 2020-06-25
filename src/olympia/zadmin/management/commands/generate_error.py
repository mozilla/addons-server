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
        parser.add_argument(
            '--log',
            default=False,
            action='store_true',
            help='capture the error inside a log.exception instead')

    def handle(self, *args, **options):
        if options.get('celery'):
            celery_error.delay(capture_and_log=options.get('log', False))
            print('A RuntimeError exception was raised from a celery task. '
                  'Check the logs!')
        else:
            print('About to raise an exception in management command')
            try:
                raise RuntimeError(
                    'This is an exception from a management command')
            except Exception as exception:
                if options.get('log', False):
                    log.exception(
                        'Capturing exception as a log', exc_info=exception)
                else:
                    raise exception
