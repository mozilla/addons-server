from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from celery import chord, group

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.tasks import (
    add_firefox57_tag, find_inconsistencies_between_es_and_db)
from olympia.amo.utils import chunked
from olympia.devhub.tasks import convert_purified, get_preview_sizes
from olympia.editors.tasks import recalculate_post_review_weight
from olympia.lib.crypto.tasks import sign_addons
from olympia.reviews.tasks import addon_review_aggregates


tasks = {
    'find_inconsistencies_between_es_and_db': {
        'method': find_inconsistencies_between_es_and_db, 'qs': []},
    'get_preview_sizes': {'method': get_preview_sizes, 'qs': []},
    'convert_purified': {'method': convert_purified, 'qs': []},
    'addon_review_aggregates': {'method': addon_review_aggregates, 'qs': []},
    'recalculate_post_review_weight': {
        'method': recalculate_post_review_weight,
        'qs': [
            Q(_current_version__autoapprovalsummary__verdict=amo.AUTO_APPROVED)
        ]},
    'sign_addons': {'method': sign_addons, 'qs': []},
    'add_firefox57_tag_to_webextensions': {
        'method': add_firefox57_tag,
        'qs': [Q(status=amo.STATUS_PUBLIC,
                 _current_version__files__is_webextension=True)]}
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
    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--task',
            action='store',
            dest='task',
            type=str,
            help='Run task on the addons.')

        parser.add_argument(
            '--with-deleted',
            action='store_true',
            dest='with_deleted',
            help='Include deleted add-ons when determining which '
                 'add-ons to process.')

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
