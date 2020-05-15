from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q, F

from celery import chord, group

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.tasks import (
    add_dynamic_theme_tag,
    delete_addons,
    extract_colors_from_static_themes,
    find_inconsistencies_between_es_and_db,
    migrate_webextensions_to_git_storage,
    recreate_theme_previews,
)
from olympia.abuse.models import AbuseReport
from olympia.constants.base import _ADDON_PERSONA, _ADDON_THEME, _ADDON_WEBAPP
from olympia.amo.utils import chunked
from olympia.devhub.tasks import get_preview_sizes, recreate_previews
from olympia.git.tasks import delete_source_git_repositories
from olympia.lib.crypto.tasks import sign_addons
from olympia.reviewers.tasks import recalculate_post_review_weight
from olympia.versions.compare import version_int
from olympia.versions.models import Version


firefox_56_star = version_int('56.*')
current_autoapprovalsummary = '_current_version__autoapprovalsummary__'


def get_recalc_needed_filters():
    summary_modified = F('_current_version__autoapprovalsummary__modified')
    # We don't take deleted reports into account
    valid_abuse_report_states = (
        AbuseReport.STATES.UNTRIAGED, AbuseReport.STATES.VALID,
        AbuseReport.STATES.SUSPICIOUS)
    return [
        # Only recalculate add-ons that received recent abuse reports
        # possibly through their authors.
        Q(
            abuse_reports__state__in=valid_abuse_report_states,
            abuse_reports__created__gte=summary_modified
        ) |
        Q(
            authors__abuse_reports__state__in=valid_abuse_report_states,
            authors__abuse_reports__created__gte=summary_modified
        ) |

        # And check ratings that have a rating of 3 or less
        Q(
            _current_version__ratings__deleted=False,
            _current_version__ratings__created__gte=summary_modified,
            _current_version__ratings__rating__lte=3)
    ]


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
    'constantly_recalculate_post_review_weight': {
        # This re-calculates the whole post-review weight which can be costly
        # so take that into account. We may want to optimize that later
        # in case we notice things are slower than needed - cgrebs 20190730
        'method': recalculate_post_review_weight,
        'kwargs': {'only_current_version': True},
        'qs': get_recalc_needed_filters()},
    'resign_addons_for_cose': {
        'method': sign_addons,
        'qs': [
            # Only resign public add-ons where the latest version has been
            # created before the 5th of April
            Q(status=amo.STATUS_APPROVED,
              _current_version__created__lt=datetime(2019, 4, 5)) &
            ~Q(type=amo.ADDON_SEARCH)
        ]
    },
    'recreate_previews': {
        'method': recreate_previews,
        'qs': [
            ~Q(type=amo.ADDON_STATICTHEME)
        ]
    },
    'recreate_theme_previews': {
        'method': recreate_theme_previews,
        'qs': [
            Q(type=amo.ADDON_STATICTHEME, status__in=[
                amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW])
        ],
        'kwargs': {'only_missing': False},
    },
    'create_missing_theme_previews': {
        'method': recreate_theme_previews,
        'qs': [
            Q(type=amo.ADDON_STATICTHEME, status__in=[
                amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW])
        ],
        'kwargs': {'only_missing': True},
    },
    'add_dynamic_theme_tag_for_theme_api': {
        'method': add_dynamic_theme_tag,
        'qs': [
            Q(status=amo.STATUS_APPROVED,
              _current_version__files__is_webextension=True)
        ]
    },
    'extract_webextensions_to_git_storage': {
        'method': migrate_webextensions_to_git_storage,
        'qs': [
            Q(type__in=(
                # Ignoring legacy add-ons and lightweight themes
                amo.ADDON_EXTENSION, amo.ADDON_STATICTHEME,
                amo.ADDON_DICT, amo.ADDON_LPAPP, amo.ADDON_SEARCH))
        ],
        'distinct': True,
        'allowed_kwargs': ('channel',),
    },
    'extract_colors_from_static_themes': {
        'method': extract_colors_from_static_themes,
        'qs': [Q(type=amo.ADDON_STATICTHEME)]
    },
    'delete_source_git_repositories': {
        'method': delete_source_git_repositories,
        'distinct': True,
        'qs': [
            Q(
                # Retrieve a list of add-on IDs that have at least one version
                # with a source git hash (which means source files have been
                # git-extracted).
                pk__in=Version.unfiltered.exclude(source_git_hash__exact='')
                # This is needed to make `.distinct()` work, see:
                # https://code.djangoproject.com/ticket/16058
                .order_by()
                .values_list('addon_id', flat=True)
                .distinct()
            )
        ],
        'allowed_kwargs': ('with_deleted',),
    },
    'delete_obsolete_addons': {
        'method': delete_addons,
        'qs': [
            Q(type__in=(_ADDON_THEME,
                        amo.ADDON_LPADDON,
                        amo.ADDON_PLUGIN,
                        _ADDON_PERSONA,
                        _ADDON_WEBAPP,
                        ))
        ],
        'allowed_kwargs': ('with_deleted',),
    },
    'disable_opensearch_addons': {
        # We're re-using the `delete_addons` method but don't allow for hard
        # deletes
        'method': delete_addons,
        'qs': [
            Q(type=amo.ADDON_SEARCH)
        ],
        'allowed_kwargs': ('with_deleted',),
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

        parser.add_argument(
            '--batch-size',
            action='store',
            dest='batch_size',
            type=int,
            default=100,
            help='Split the add-ons into X size chunks. Default 100.')

        parser.add_argument(
            '--channel',
            action='store',
            dest='channel',
            type=str,
            choices=('listed', 'unlisted'),
            help=(
                'Only select add-ons who have either listed or unlisted '
                'versions. Add-ons that have both will be returned too.'))

    def get_pks(self, manager, q_objects, distinct=False):
        pks = (manager.filter(q_objects)
                      .values_list('pk', flat=True)
                      .order_by('id'))
        if distinct:
            pks = pks.distinct()
        return pks

    def handle(self, *args, **options):
        task = tasks.get(options.get('task'))
        if not task:
            raise CommandError('Unknown task provided. Options are: %s'
                               % ', '.join(tasks.keys()))
        if options.get('with_deleted'):
            addon_manager = Addon.unfiltered
        else:
            addon_manager = Addon.objects
        if options.get('channel'):
            channel = amo.CHANNEL_CHOICES_LOOKUP[options['channel']]
            addon_manager = addon_manager.filter(versions__channel=channel)
        if options.get('ids'):
            ids_list = options.get('ids').split(',')
            addon_manager = addon_manager.filter(id__in=ids_list)

        pks = self.get_pks(
            addon_manager, *task['qs'], distinct=task.get('distinct'))
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
            for chunk in chunked(pks, options.get('batch_size')):
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
