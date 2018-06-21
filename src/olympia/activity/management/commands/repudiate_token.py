from django.core.management.base import BaseCommand, CommandError

import olympia.core.logger

from olympia.activity.models import ActivityLogToken


class Command(BaseCommand):
    help = u'Force expire a list of Activity Email tokens.'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('token_uuid', nargs='*')
        parser.add_argument(
            '--version_id', action='store', type=long,
            dest='version_id',
            help='Expire all tokens on this version.')

    def handle(self, *args, **options):
        version_pk = options.get('version_id')
        token_uuids = options.get('token_uuid')
        if token_uuids:
            done = [t.expire() for t in ActivityLogToken.objects.filter(
                uuid__in=token_uuids)]
            log.info(
                u'%s tokens (%s) expired' % (len(done), ','.join(token_uuids)))
            if version_pk:
                print('Warning: --version_id ignored as tokens provided too')
        elif version_pk:
            done = [t.expire() for t in ActivityLogToken.objects.filter(
                version__pk=version_pk)]
            log.info(
                u'%s tokens for version %s expired' % (len(done), version_pk))
        else:
            raise CommandError(
                u'Please provide either at least one token, or a version id.')
