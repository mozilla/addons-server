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
    auto-approved add-on current version from a list of add-on ids."""
    addons = Addon.objects.filter(id__in=ids)
    for addon in addons:
        summary = AutoApprovalSummary.objects.get(version=addon.current_version)

        old_weight = summary.weight
        old_code_weight = summary.code_weight
        old_metadata_weight = summary.metadata_weight
        summary.calculate_weight()
        if (
            summary.weight != old_weight
            or summary.metadata_weight != old_metadata_weight
            or summary.code_weight != old_code_weight
        ):
            summary.save()
