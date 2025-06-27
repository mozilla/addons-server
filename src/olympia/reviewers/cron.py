from datetime import date

from olympia.constants.promoted import (
    PROMOTED_GROUPS,
)
from olympia.reviewers.models import QueueCount
from olympia.reviewers.utils import PendingManualApprovalQueueTable
from olympia.reviewers.views import reviewer_tables_registry


def record_reviewer_queues_counts():
    today = date.today()
    # Grab a queryset for each reviewer queue.
    querysets = {
        queue.name: queue.get_queryset(None)
        for queue in reviewer_tables_registry.values()
    }
    # Also drill down manual review queue by promoted class (there is no real
    # queue for each, but we still want that data).
    for group in PROMOTED_GROUPS:
        querysets[f'{PendingManualApprovalQueueTable.name}/{group.api_name}'] = (
            PendingManualApprovalQueueTable.get_queryset(None).filter(
                promotedaddon__promoted_group__group_id=group.id
            )
        )

    # Execute a count for each queryset and record a QueueCount instance for it
    for key, qs in querysets.items():
        QueueCount.objects.get_or_create(
            name=key, date=today, defaults={'value': qs.optimized_count()}
        )
