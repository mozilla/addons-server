from django.core.management.base import BaseCommand, CommandError

import olympia.core.logger
from olympia.activity.models import ActivityLogToken


log = olympia.core.logger.getLogger('z.amo.activity')


class Command(BaseCommand):
    help = 'Force expire a list of Activity Email tokens.'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('token_uuid', nargs='*')
        parser.add_argument(
            '--version_id',
            action='store',
            type=int,
            dest='version_id',
            help='Expire all tokens on this version.',
        )

    def handle(self, *args, **options):
        version_pk = options.get('version_id')
        token_uuids = options.get('token_uuid')
        if token_uuids:
            done = [
                t.expire()
                for t in ActivityLogToken.objects.filter(uuid__in=token_uuids)
            ]
            log.info('{} tokens ({}) expired'.format(len(done), ','.join(token_uuids)))
            if version_pk:
                print('Warning: --version_id ignored as tokens provided too')
        elif version_pk:
            done = [
                t.expire()
                for t in ActivityLogToken.objects.filter(version__pk=version_pk)
            ]
            log.info(f'{len(done)} tokens for version {version_pk} expired')
        else:
            raise CommandError(
                'Please provide either at least one token, or a version id.'
            )
