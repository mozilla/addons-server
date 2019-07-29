from django.db.models import F, Q

import olympia.core.logger

from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.reviewers.models import AutoApprovalSummary


log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
def recalculate_post_review_weight(ids):
    """Recalculate the post-review weight that should be assigned to
    auto-approved add-on versions from a list of ids."""
    addons = Addon.objects.filter(id__in=ids)
    for addon in addons:
        summaries = AutoApprovalSummary.objects.filter(
            version__in=addon.versions.all())

        for summary in summaries:
            summary.calculate_weight()
            summary.save()


def get_recalc_needed_filters():
    cv = '_current_version__'
    summary_modified = F(f'{cv}autoapprovalsummary__modified')

    return [
        # Only recalculate add-ons that received recent abuse reports
        # possibly through their authors.
        Q(**{
            'abuse_reports__created__gte': summary_modified}) |
        Q(**{
            'authors__abuse_reports__created__gte': summary_modified
        }) |

        # And check ratings that have a rating of 3 or less
        Q(**{
            f'{cv}ratings__created__gte': summary_modified,
            f'{cv}ratings__rating__lte': 3
        })
    ]
