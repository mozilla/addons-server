import argparse

from datetime import datetime
from importlib import import_module

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from olympia.core import logger


log = logger.getLogger('z.cron')


class Command(BaseCommand):
    help = 'Run one of the predefined cron jobs'

    def add_arguments(self, parser):
        # We handle the case where 0 arguments are given specifically below,
        # so use nargs='?' for the first argument.
        parser.add_argument('name', nargs='?')
        parser.add_argument('cron_args', nargs=argparse.REMAINDER, default=[])

    def handle(self, *args, **options):
        if not options['name']:
            log.error("Cron called without args")
            raise CommandError('These jobs are available:\n%s' % '\n'.join(
                sorted(settings.CRON_JOBS.keys())))

        name, args_and_kwargs = options['name'], options['cron_args']
        args = [arg for arg in args_and_kwargs if '=' not in arg]
        kwargs = dict(
            (kwarg.split('=', maxsplit=1) for kwarg in args_and_kwargs
             if kwarg not in args))

        path = settings.CRON_JOBS.get(name)
        if not path:
            log.error(
                'Cron called with an unknown cron job: '
                f'{name} {args} {kwargs}')
            raise CommandError(f'Unrecognized job name: {name}')

        module = import_module(path)

        current_millis = datetime.now().timestamp() * 1000

        log.info(
            f'Beginning job: {name} {args} {kwargs} '
            f'(start timestamp: {current_millis})')
        getattr(module, name)(*args, **kwargs)
        log.info(
            f'Ending job: {name} {args} {kwargs} '
            f'(start timestamp: {current_millis})')
