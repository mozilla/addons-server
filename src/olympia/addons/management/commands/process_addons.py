from optparse import make_option

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from celery import chord, group

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.tasks import (
    find_inconsistencies_between_es_and_db, remove_summaries)
from olympia.amo.utils import chunked
from olympia.devhub.tasks import convert_purified, get_preview_sizes
from olympia.lib.crypto.tasks import sign_addons
from olympia.reviews.tasks import addon_review_aggregates


tasks = {
    'find_inconsistencies_between_es_and_db': {
        'method': find_inconsistencies_between_es_and_db, 'qs': []},
    'get_preview_sizes': {'method': get_preview_sizes, 'qs': []},
    'convert_purified': {'method': convert_purified, 'qs': []},
    'addon_review_aggregates': {'method': addon_review_aggregates, 'qs': []},
    'sign_addons': {'method': sign_addons, 'qs': []},
    'remove-summaries-from-personas': {
        'method': remove_summaries,
        'qs': [Q(type=amo.ADDON_PERSONA, summary__isnull=False)]},
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
        make_option('--with-deleted', action='store_true',
                    dest='with_deleted',
                    help='Include deleted add-ons when determining which '
                         'add-ons to process.'),
    )

    def handle(self, *args, **options):
        task = tasks.get(options.get('task'))
        if not task:
            raise CommandError('Unknown task provided. Options are: %s'
                               % ', '.join(tasks.keys()))
        if options.get('with_deleted'):
            addon_manager = Addon.unfiltered
        else:
            addon_manager = Addon.objects
        pks = (addon_manager.filter(*task['qs'])
                            .values_list('pk', flat=True)
                            .order_by('id'))
        if 'pre' in task:
            # This is run in process to ensure its run before the tasks.
            pks = task['pre'](pks)
        if pks:
            kw = task.get('kwargs', {})
            # All the remaining tasks go in one group.
            grouping = []
            for chunk in chunked(pks, 100):
                grouping.append(
                    task['method'].subtask(args=[chunk], kwargs=kw))

            # Add the post task on to the end.
            post = None
            if 'post' in task:
                post = task['post'].subtask(args=[], kwargs=kw, immutable=True)
                ts = chord(grouping, post)
            else:
                ts = group(grouping)
            ts.apply_async()
