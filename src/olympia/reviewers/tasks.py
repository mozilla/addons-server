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
