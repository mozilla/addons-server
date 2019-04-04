from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from celery import chord, group

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.tasks import (
    add_dynamic_theme_tag,
    delete_addons,
    extract_colors_from_static_themes,
    find_inconsistencies_between_es_and_db,
    migrate_lwts_to_static_themes,
    migrate_webextensions_to_git_storage,
    recreate_theme_previews)
from olympia.amo.utils import chunked
from olympia.devhub.tasks import get_preview_sizes, recreate_previews
from olympia.lib.crypto.tasks import sign_addons
from olympia.reviewers.tasks import recalculate_post_review_weight
from olympia.versions.compare import version_int


firefox_56_star = version_int('56.*')
current_autoapprovalsummary = '_current_version__autoapprovalsummary__'


tasks = {
    'find_inconsistencies_between_es_and_db': {
        'method': find_inconsistencies_between_es_and_db, 'qs': []},
    'get_preview_sizes': {'method': get_preview_sizes, 'qs': []},
    'recalculate_post_review_weight': {
        'method': recalculate_post_review_weight,
        'qs': [
            Q(**{current_autoapprovalsummary + 'verdict': amo.AUTO_APPROVED}) &
            ~Q(**{current_autoapprovalsummary + 'confirmed': True})
        ]},
    'sign_addons': {
        'method': sign_addons,
        'qs': []},
    'migrate_lwt': {
        'method': migrate_lwts_to_static_themes,
        'qs': [
            Q(type=amo.ADDON_PERSONA, status=amo.STATUS_PUBLIC)
        ]
    },
    'delete_lwt': {
        'method': delete_addons,
        'qs': [
            Q(type=amo.ADDON_PERSONA)
        ]
    },
    'recreate_previews': {
        'method': recreate_previews,
        'qs': [
            ~Q(type=amo.ADDON_PERSONA)
        ]
    },
    'recreate_theme_previews': {
        'method': recreate_theme_previews,
        'qs': [
            Q(type=amo.ADDON_STATICTHEME, status__in=[
                amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW])
        ],
        'kwargs': {'only_missing': False},
    },
    'create_missing_theme_previews': {
        'method': recreate_theme_previews,
        'qs': [
            Q(type=amo.ADDON_STATICTHEME, status__in=[
                amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW])
        ],
        'kwargs': {'only_missing': True},
    },
    'add_dynamic_theme_tag_for_theme_api': {
        'method': add_dynamic_theme_tag,
        'qs': [
            Q(status=amo.STATUS_PUBLIC,
              _current_version__files__is_webextension=True)
        ]
    },
    'extract_webextensions_to_git_storage': {
        'method': migrate_webextensions_to_git_storage,
        'qs': [
            Q(_current_version__files__is_webextension=True,
              type__in=(
                  # Ignoring legacy add-ons and lightweight themes
                  amo.ADDON_EXTENSION, amo.ADDON_STATICTHEME,
                  amo.ADDON_DICT, amo.ADDON_LPAPP)) |
            Q(type=amo.ADDON_SEARCH)
        ]
    },
    'extract_colors_from_static_themes': {
        'method': extract_colors_from_static_themes,
        'qs': [Q(type=amo.ADDON_STATICTHEME)]
    }
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
    allowed_kwargs: any extra boolean kwargs that can be applied via
        additional arguments. Make sure to add it to `add_arguments` too.
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

        parser.add_argument(
            '--ids',
            action='store',
            dest='ids',
            help='Only apply task to specific addon ids (comma-separated).')

        parser.add_argument(
            '--limit',
            action='store',
            dest='limit',
            type=int,
            help='Only apply task to the first X addon ids.')

    def handle(self, *args, **options):
        task = tasks.get(options.get('task'))
        if not task:
            raise CommandError('Unknown task provided. Options are: %s'
                               % ', '.join(tasks.keys()))
        if options.get('with_deleted'):
            addon_manager = Addon.unfiltered
        else:
            addon_manager = Addon.objects
        if options.get('ids'):
            ids_list = options.get('ids').split(',')
            addon_manager = addon_manager.filter(id__in=ids_list)
        pks = (addon_manager.filter(*task['qs'])
                            .values_list('pk', flat=True)
                            .order_by('id'))
        if options.get('limit'):
            pks = pks[:options.get('limit')]
        if 'pre' in task:
            # This is run in process to ensure its run before the tasks.
            pks = task['pre'](pks)
        if pks:
            kwargs = task.get('kwargs', {})
            if task.get('allowed_kwargs'):
                kwargs.update({
                    arg: options.get(arg, None)
                    for arg in task['allowed_kwargs']})
            # All the remaining tasks go in one group.
            grouping = []
            for chunk in chunked(pks, 100):
                grouping.append(
                    task['method'].subtask(args=[chunk], kwargs=kwargs))

            # Add the post task on to the end.
            post = None
            if 'post' in task:
                post = task['post'].subtask(
                    args=[], kwargs=kwargs, immutable=True)
                ts = chord(grouping, post)
            else:
                ts = group(grouping)
            ts.apply_async()
