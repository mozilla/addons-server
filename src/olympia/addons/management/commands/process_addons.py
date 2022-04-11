from datetime import datetime

from django.db.models import Q, F

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.tasks import (
    delete_addons,
    extract_colors_from_static_themes,
    find_inconsistencies_between_es_and_db,
    recreate_theme_previews,
)
from olympia.abuse.models import AbuseReport
from olympia.constants.base import _ADDON_PERSONA, _ADDON_THEME, _ADDON_WEBAPP
from olympia.amo.management import ProcessObjectsCommand
from olympia.devhub.tasks import get_preview_sizes, recreate_previews
from olympia.lib.crypto.tasks import sign_addons
from olympia.ratings.tasks import addon_rating_aggregates
from olympia.reviewers.tasks import recalculate_post_review_weight
from olympia.versions.tasks import delete_list_theme_previews


class Command(ProcessObjectsCommand):
    def get_model(self):
        return Addon

    def get_tasks(self):
        def get_recalc_needed_filters():
            summary_modified = F('_current_version__autoapprovalsummary__modified')
            # We don't take deleted reports into account
            valid_abuse_report_states = (
                AbuseReport.STATES.UNTRIAGED,
                AbuseReport.STATES.VALID,
                AbuseReport.STATES.SUSPICIOUS,
            )

            return [
                # Only recalculate add-ons that received recent abuse reports
                # possibly through their authors.
                Q(
                    abuse_reports__state__in=valid_abuse_report_states,
                    abuse_reports__created__gte=summary_modified,
                )
                | Q(
                    authors__abuse_reports__state__in=valid_abuse_report_states,
                    authors__abuse_reports__created__gte=summary_modified,
                )
                # And check ratings that have a rating of 3 or less
                | Q(
                    _current_version__ratings__deleted=False,
                    _current_version__ratings__created__gte=summary_modified,
                    _current_version__ratings__rating__lte=3,
                )
            ]

        return {
            'find_inconsistencies_between_es_and_db': {
                'task': find_inconsistencies_between_es_and_db,
                'queryset_filters': [],
            },
            'get_preview_sizes': {'task': get_preview_sizes, 'queryset_filters': []},
            'recalculate_post_review_weight': {
                'task': recalculate_post_review_weight,
                'queryset_filters': [
                    Q(_current_version__autoapprovalsummary__verdict=amo.AUTO_APPROVED)
                    & ~Q(_current_version__autoapprovalsummary__confirmed=True)
                ],
            },
            'constantly_recalculate_post_review_weight': {
                'task': recalculate_post_review_weight,
                'queryset_filters': get_recalc_needed_filters(),
            },
            'resign_addons_for_cose': {
                'task': sign_addons,
                'queryset_filters': [
                    # Only resign public add-ons where the latest version has been
                    # created before the 5th of April
                    Q(
                        status=amo.STATUS_APPROVED,
                        _current_version__created__lt=datetime(2019, 4, 5),
                    )
                ],
            },
            'recreate_previews': {
                'task': recreate_previews,
                'queryset_filters': [~Q(type=amo.ADDON_STATICTHEME)],
            },
            'recreate_theme_previews': {
                'task': recreate_theme_previews,
                'queryset_filters': [
                    Q(
                        type=amo.ADDON_STATICTHEME,
                        status__in=[amo.STATUS_APPROVED, amo.STATUS_NOMINATED],
                    )
                ],
                'kwargs': {'only_missing': False},
            },
            'create_missing_theme_previews': {
                'task': recreate_theme_previews,
                'queryset_filters': [
                    Q(
                        type=amo.ADDON_STATICTHEME,
                        status__in=[amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW],
                    )
                ],
                'kwargs': {'only_missing': True},
            },
            'delete_list_theme_previews': {
                'task': delete_list_theme_previews,
                'queryset_filters': [
                    Q(
                        type=amo.ADDON_STATICTHEME,
                    )
                ],
            },
            'extract_colors_from_static_themes': {
                'task': extract_colors_from_static_themes,
                'queryset_filters': [Q(type=amo.ADDON_STATICTHEME)],
            },
            'delete_obsolete_addons': {
                'task': delete_addons,
                'queryset_filters': [
                    Q(
                        type__in=(
                            _ADDON_THEME,
                            amo.ADDON_LPADDON,
                            _ADDON_PLUGIN,
                            _ADDON_PERSONA,
                            _ADDON_WEBAPP,
                        )
                    )
                ],
                'allowed_kwargs': ('with_deleted',),
            },
            'update_rating_aggregates': {
                'task': addon_rating_aggregates,
                'queryset_filters': [Q(status=amo.STATUS_APPROVED)],
            },
        }

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            '--channel',
            action='store',
            dest='channel',
            type=str,
            choices=('listed', 'unlisted'),
            help=(
                'Only select add-ons who have either listed or unlisted '
                'versions. Add-ons that have both will be returned too.'
            ),
        )

    def get_base_queryset(self, options):
        base_qs = super().get_base_queryset(options)
        if options.get('channel'):
            channel = amo.CHANNEL_CHOICES_LOOKUP[options['channel']]
            base_qs = base_qs.filter(versions__channel=channel)
        return base_qs
