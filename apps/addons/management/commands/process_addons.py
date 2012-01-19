from optparse import make_option

from django.core.management.base import BaseCommand
from django.db.models import Q

import amo
from addons.models import Addon
from amo.utils import chunked
from devhub.tasks import convert_purified, flag_binary, get_preview_sizes


tasks = {
    # binary-components depend on having a chrome manifest.
    'flag_binary_components': {'method': flag_binary,
                               'qs': [Q(type__in=[amo.ADDON_EXTENSION,
                                                  amo.ADDON_DICT,
                                                  amo.ADDON_LPADDON,
                                                  amo.ADDON_PLUGIN,
                                                  amo.ADDON_API]),
                                      Q(disabled_by_user=False)],
                               'kwargs': dict(latest=False)},
    'flag_binary': {'method': flag_binary, 'qs': []},
    'get_preview_sizes': {'method': get_preview_sizes, 'qs': []},
    'convert_purified': {'method': convert_purified, 'qs': []}
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
                            .order_by('-last_updated'))
        for chunk in chunked(pks, 100):
            if task.get('kwargs'):
                task['method'].delay(chunk, **task.get('kwargs'))
            else:
                task['method'].delay(chunk)
