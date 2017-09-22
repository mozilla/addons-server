from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from celery import chord, group

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.tasks import (
    add_firefox57_tag, bump_appver_for_legacy_addons,
    find_inconsistencies_between_es_and_db)
from olympia.amo.utils import chunked
from olympia.devhub.tasks import convert_purified, get_preview_sizes
from olympia.editors.tasks import recalculate_post_review_weight
from olympia.lib.crypto.tasks import sign_addons
from olympia.versions.compare import version_int


firefox_56_star = version_int('56.*')


tasks = {
    'find_inconsistencies_between_es_and_db': {
        'method': find_inconsistencies_between_es_and_db, 'qs': []},
    'get_preview_sizes': {'method': get_preview_sizes, 'qs': []},
    'convert_purified': {'method': convert_purified, 'qs': []},
    'recalculate_post_review_weight': {
        'method': recalculate_post_review_weight,
        'qs': [
            Q(_current_version__autoapprovalsummary__verdict=amo.AUTO_APPROVED)
        ]},
    'sign_addons': {'method': sign_addons, 'qs': []},
    'add_firefox57_tag_to_webextensions': {
        'method': add_firefox57_tag,
        'qs': [
            Q(status=amo.STATUS_PUBLIC) & (
                Q(_current_version__files__is_webextension=True) |
                Q(_current_version__files__is_mozilla_signed_extension=True)
            )
        ]},
    'bump_appver_for_legacy_addons': {
        'method': bump_appver_for_legacy_addons,
        'qs': [
            Q(
                type__in=(amo.ADDON_EXTENSION, amo.ADDON_THEME),
                _current_version__files__is_webextension=False,
                _current_version__apps__max__version_int__lt=firefox_56_star,
                _current_version__apps__application__in=(
                    amo.FIREFOX.id, amo.ANDROID.id))
        ],
        'pre': lambda values_qs: values_qs.distinct(),
    },
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
