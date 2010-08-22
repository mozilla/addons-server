from django.core.management.base import BaseCommand, CommandError
from optparse import make_option
from celery.messaging import establish_connection
import commonware.log

## FIXME: reasonable name?
log = commonware.log.getLogger('z.command')


class Command(BaseCommand):

    option_list = BaseCommand.option_list + (
        make_option('--max-objs', metavar='NUMBER',
                    help="Maximum number of objects to update in a session "
                    "(non-zero exit code if there are more objects)"),
        make_option('--queue', action='store_true',
                    help="Queue this job to Celery instead of running it "
                    "immediately"),
        make_option('--class', dest='classes', action='append',
                    help="Only update the given class (use multiple times "
                    "for multiple classes)"),
        make_option('--addon-id', dest='addon_ids', action='append',
                    help="Only update the given addon_id(s)"),
        make_option('--simulate', action='store_true',
                    help="Simulate (don't actually update server)")
        )

    def handle(self, *args, **options):
        from stats.tasks import update_to_json, _JSONUpdater
        max_objs = int(options.get('max_objs', 0) or '0') or None
        ids = [] if not options.get('addon_ids') else [int(i) for i in options.get('addon_ids')]
        classes = options.get('classes') or []
        if options.get('simulate') and options.get('queue'):
            raise CommandError('Cannot use --simulate and --queue together')
        if options.get('queue'):
            with establish_connection() as conn:
                update_to_json.apply_async(max_objs=max_objs,
                                           connection=conn,
                                           classes=classes,
                                           ids=ids)
        else:
            updater = _JSONUpdater(max_objs, log, self.after_exit,
                                   classes=classes, ids=ids,
                                   simulate=options.get('simulate'))
            updater.run()

    def after_exit(self, msg):
        raise CommandError(msg)
