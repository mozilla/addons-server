from optparse import make_option

from django.core.management.base import BaseCommand
from django.db.models import Q

import amo
from addons.models import Addon
from amo.utils import chunked
from devhub.tasks import convert_purified, flag_binary, get_preview_sizes
from market.tasks import check_paypal, check_paypal_multiple
from mkt.webapps.tasks import update_manifests

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
    'convert_purified': {'method': convert_purified, 'qs': []},
    'check_paypal': {'pre': check_paypal_multiple,
                     'method': check_paypal,
                     'qs': [Q(premium_type=amo.ADDON_PREMIUM,
                              disabled_by_user=False),
                            ~Q(status=amo.STATUS_DISABLED)]},
    'update_manifests': {'method': update_manifests,
                         'qs': [Q(type=amo.ADDON_WEBAPP, is_packaged=False,
                                  status=amo.STATUS_PUBLIC,
                                  disabled_by_user=False)]},
}


class Command(BaseCommand):
    """
    A generic command to run a task on addons.
    Add tasks to the tasks dictionary, providing a list of Q objects if you'd
    like to filter the list down.

    method: the method to delay
    pre: a method to further pre process the pks, must return the pks (opt.)
    qs: a list of Q objects to apply to the method
    kwargs: any extra kwargs you want to apply to the delay method (optional)
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
        if 'pre' in task:
            pks = task['pre'](pks)
        if pks:
            for chunk in chunked(pks, 100):
                task['method'].delay(chunk, **task.get('kwargs', {}))
