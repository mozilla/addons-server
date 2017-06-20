from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

import olympia.core.logger
from olympia.activity.models import ActivityLogToken

log = olympia.core.logger.getLogger('z.amo.activity')


class Command(BaseCommand):
    args = u'<token_uuid token_uuid ...>'
    help = u'Force expire a list of Activity Email tokens.'

    option_list = BaseCommand.option_list + (
        make_option('--version_id', action='store', type='long',
                    dest='version_id',
                    help='Expire all tokens on this version.'),
    )

    def handle(self, *args, **options):
        version_pk = options.get('version_id')
        if len(args) > 0:
            done = [t.expire() for t in ActivityLogToken.objects.filter(
                uuid__in=args)]
            log.info(u'%s tokens (%s) expired' % (len(done), ','.join(args)))
            if version_pk:
                print 'Warning: --version_id ignored as tokens provided too'
        elif version_pk:
            done = [t.expire() for t in ActivityLogToken.objects.filter(
                version__pk=version_pk)]
            log.info(
                u'%s tokens for version %s expired' % (len(done), version_pk))
        else:
            raise CommandError(
                u'Please provide either at least one token, or a version id.')
