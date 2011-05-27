from optparse import make_option

from django.core.management.base import BaseCommand

from addons.models import Addon
from amo.utils import chunked
from devhub.tasks import flag_binary

from celery.messaging import establish_connection

tasks = {
    'flag_binary': flag_binary,
}


class Command(BaseCommand):
    """
    A generic command to run a task on *all* addons.
    Add tasks to the reg dictionary.
    """
    option_list = BaseCommand.option_list + (
        make_option('--task', action='store', type='string',
                    dest='task', help='Run task on all addons.'),
    )

    def handle(self, *args, **options):
        pks = Addon.objects.values_list('pk', flat=True).order_by('id')
        task = tasks.get(options.get('task'))
        if not task:
            raise ValueError('Unknown task: %s' % ', '.join(tasks.keys()))
        with establish_connection():
            for chunk in chunked(pks, 100):
                task.delay(chunk)
