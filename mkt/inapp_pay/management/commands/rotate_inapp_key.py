from optparse import make_option

from django.conf import settings
from django.db import transaction
from django.core.management.base import BaseCommand, CommandError

from mkt.inapp_pay.models import InappConfig


class Command(BaseCommand):
    help = 'Migrate all encrypted in-app values to use a new encryption key.'
    option_list = BaseCommand.option_list + (
        make_option('--old-timestamp', action='store',
                    help='Old timestamp for key in settings.INAPP_KEY_PATHS'),
        make_option('--new-timestamp', action='store',
                    help='New timestamp for key in settings.INAPP_KEY_PATHS'),
    )

    def handle(self, *args, **options):
        if (not options.get('old_timestamp') or not
            options.get('new_timestamp')):
            raise CommandError('Options --old-timestamp and --new-timestamp '
                               'are required.')
        if options['old_timestamp'] not in settings.INAPP_KEY_PATHS:
            raise CommandError('Old key %r must still be on disk and in '
                               'settings.INAPP_KEY_PATHS during migration'
                               % options['old_timestamp'])
        if options['new_timestamp'] not in settings.INAPP_KEY_PATHS:
            raise CommandError('New key %r must be on disk and in '
                               'settings.INAPP_KEY_PATHS during migration'
                               % options['new_timestamp'])
        if len(settings.INAPP_KEY_PATHS.keys()) > 2:
            raise CommandError('Cannot do an accurate migration when there '
                               'are more than two keys in use.')
        num = 0
        print 'migrating keys...'
        with transaction.commit_on_success():
            for cfg in (InappConfig.uncached
                                   .exclude(_encrypted_private_key=None)):
                InappConfig.objects.invalidate(cfg)
                num += 1
                old_val = cfg.get_private_key()
                cfg.set_private_key(old_val)
        print 'Values migrated to new encryption key: %s' % num
        print ('It is now safe to remove key %r from disk and settings'
               % options['old_timestamp'])
