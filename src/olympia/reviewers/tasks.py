from django.conf import settings

import olympia.core.logger
from olympia.addons.models import Addon
from olympia import amo
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.reviewers.models import AutoApprovalSummary
from olympia.versions.models import Version


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


@task
@use_primary_db
def create_zendesk_ticket(version_pk):
    """Create a Zendesk ticket for a version that requires manual review."""
    if not settings.ZENDESK_API_TOKEN:
        return

    from olympia.reviewers.models import ZendeskTicket
    from olympia.reviewers.zendesk import (
        ZendeskClient,
        build_ticket_body,
        build_ticket_collaborators,
        build_ticket_custom_fields,
        build_ticket_requester,
        get_addon_primary_author,
    )

    if ZendeskTicket.objects.filter(version_id=version_pk).exists():
        return

    try:
        version = Version.objects.get(pk=version_pk)
    except Version.DoesNotExist:
        log.info('create_zendesk_ticket: version %s not found, skipping', version_pk)
        return

    subject = f'Add-on Review: {version.addon.name} {version.version}'

    try:
        client = ZendeskClient()
        ticket_id, zendesk_requester_id = client.create_ticket(
            subject=subject,
            body=build_ticket_body(version),
            external_id=str(version_pk),
            brand_id=settings.ZENDESK_AMO_BRAND_ID or None,
            requester=build_ticket_requester(version),
            collaborators=build_ticket_collaborators(version),
            custom_fields=build_ticket_custom_fields(version),
        )
        ZendeskTicket.objects.create(version_id=version_pk, ticket_id=ticket_id)
        log.info('Created Zendesk ticket #%s for version %s', ticket_id, version_pk)
    except Exception:
        log.exception('Failed to create Zendesk ticket for version %s', version_pk)
        return

    if zendesk_requester_id:
        author = get_addon_primary_author(version.addon)
        if author and author.fxa_id:
            try:
                client.set_user_fxa_id(zendesk_requester_id, author.fxa_id)
            except Exception:
                log.exception(
                    'Failed to set FxA ID on Zendesk user for version %s', version_pk
                )


@task
@use_primary_db
def add_zendesk_comment_for_activity_log(activity_log_id):
    """Add a private Zendesk comment mirroring an AMO activity log entry."""
    if not settings.ZENDESK_API_TOKEN:
        return

    from olympia.activity.models import ActivityLog
    from olympia.reviewers.models import ZendeskTicket
    from olympia.reviewers.zendesk import ZendeskClient, build_comment_body

    try:
        log_entry = ActivityLog.objects.get(pk=activity_log_id)
    except ActivityLog.DoesNotExist:
        log.info(
            'add_zendesk_comment: activity log %s not found, skipping', activity_log_id
        )
        return

    version_pks = list(log_entry.versionlog_set.values_list('version_id', flat=True))
    tickets = list(ZendeskTicket.objects.filter(version_id__in=version_pks))
    if not tickets:
        return

    body = build_comment_body(log_entry)
    client = ZendeskClient()
    for ticket in tickets:
        try:
            client.add_comment(ticket.ticket_id, body, public=False)
            log.info(
                'Added comment to Zendesk ticket #%s for activity log %s',
                ticket.ticket_id,
                activity_log_id,
            )
        except Exception:
            log.exception(
                'Failed to add comment to Zendesk ticket #%s for activity log %s',
                ticket.ticket_id,
                activity_log_id,
            )


@task
@use_primary_db
def close_zendesk_ticket(version_pk):
    """Close the Zendesk ticket associated with a version, if one exists."""
    if not settings.ZENDESK_API_TOKEN:
        return

    from olympia.reviewers.models import ZendeskTicket
    from olympia.reviewers.zendesk import ZendeskClient

    try:
        zt = ZendeskTicket.objects.get(version_id=version_pk)
    except ZendeskTicket.DoesNotExist:
        return

    try:
        ZendeskClient().close_ticket(zt.ticket_id)
        log.info('Closed Zendesk ticket #%s for version %s', zt.ticket_id, version_pk)
    except Exception:
        log.exception(
            'Failed to close Zendesk ticket #%s for version %s',
            zt.ticket_id,
            version_pk,
        )
