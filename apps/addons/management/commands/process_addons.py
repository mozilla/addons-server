from optparse import make_option

from django.core.management.base import BaseCommand
from django.db.models import Q

from addons.models import Addon
from addons.tasks import fix_get_satisfaction
from amo.utils import chunked
from devhub.tasks import flag_binary

tasks = {
    'flag_binary': {'method': flag_binary, 'qs': []},
    'fix_get_satisfaction': {
        'method': fix_get_satisfaction,
        'qs': [Q(get_satisfaction_company__startswith='http')],
    }
}


class Command(BaseCommand):
    """
    A generic command to run a task on addons.
    Add tasks to the tasks dictionary, providing a list of Q objects if you'd
    like to filter the list down.
    """
    option_list = BaseCommand.option_list + (
        make_option('--task', action='store', type='string',
                    dest='task', help='Run task on the addons.'),
    )

    def handle(self, *args, **options):
        task = tasks.get(options.get('task'))
        if not task:
            raise ValueError('Unknown task: %s' % ', '.join(tasks.keys()))
        pks = (Addon.objects.filter(*task['qs'])
                            .values_list('pk', flat=True)
                            .order_by('id'))
        for chunk in chunked(pks, 100):
            task['method'].delay(chunk)
