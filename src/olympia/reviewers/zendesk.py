import requests
from django.conf import settings

import olympia.core.logger
from django.urls import reverse

from olympia.amo.templatetags.jinja_helpers import absolutify


log = olympia.core.logger.getLogger('z.reviewers.zendesk')


class ZendeskClient:
    """HTTP client for the Zendesk Ticketing API.

    Uses API token authentication: {email}/token:{api_token}
    See https://developer.zendesk.com/api-reference/ticketing/introduction/
    """

    def __init__(self):
        self.base_url = f'https://{settings.ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/'
        self.auth = (
            f'{settings.ZENDESK_API_EMAIL}/token',
            settings.ZENDESK_API_TOKEN,
        )

    def _request(self, method, endpoint, **kwargs):
        url = f'{self.base_url}{endpoint}'
        response = requests.request(method, url, auth=self.auth, **kwargs)
        if not response.ok:
            log.error(
                'Zendesk API error %s %s: %s', response.status_code, url, response.text
            )
        response.raise_for_status()
        return response.json()

    def create_ticket(
        self,
        *,
        subject,
        body,
        external_id,
        brand_id=None,
        requester=None,
        collaborators=None,
        custom_fields=None,
    ):
        """Create a Zendesk ticket and return (ticket_id, requester_id).

        requester is a dict {"name": str, "email": str}. If the email does not
        correspond to an existing Zendesk user, Zendesk creates an end-user on
        the fly.

        custom_fields is a list of {"id": <int>, "value": <str>} dicts.
        """
        data = {
            'ticket': {
                'subject': subject,
                'comment': {'body': body, 'public': False},
                'external_id': external_id,
            }
        }
        if brand_id is not None:
            data['ticket']['brand_id'] = brand_id
        if requester is not None:
            data['ticket']['requester'] = requester
        if collaborators:
            data['ticket']['collaborators'] = collaborators
        if custom_fields:
            data['ticket']['custom_fields'] = custom_fields
        result = self._request('POST', 'tickets.json', json=data)
        ticket = result['ticket']
        return str(ticket['id']), ticket.get('requester_id')

    def set_user_fxa_id(self, zendesk_user_id, fxa_id):
        """Set the user_id custom user field on a Zendesk user to the FxA UID."""
        data = {'user': {'user_fields': {'user_id': fxa_id}}}
        self._request('PUT', f'users/{zendesk_user_id}.json', json=data)

    def get_current_user_id(self):
        """Return the Zendesk user ID of the authenticated API user."""
        result = self._request('GET', 'users/me.json')
        return result['user']['id']

    def close_ticket(self, ticket_id):
        """Mark a Zendesk ticket as solved.

        Zendesk requires an assignee before solving, so we assign it to the
        API user if none is set yet.
        """
        ticket = self._request('GET', f'tickets/{ticket_id}.json')['ticket']
        data = {'ticket': {'status': 'solved'}}
        if not ticket.get('assignee_id'):
            data['ticket']['assignee_id'] = self.get_current_user_id()
        self._request('PUT', f'tickets/{ticket_id}.json', json=data)

    def add_comment(self, ticket_id, body, public=False):
        """Add a comment to a Zendesk ticket."""
        data = {'ticket': {'comment': {'body': body, 'public': public}}}
        self._request('PUT', f'tickets/{ticket_id}.json', json=data)


def build_ticket_body(version):
    """Return a Markdown-formatted body for a new review ticket.

    Some of these fields can be moved to custom fields in follow-ups if needed.
    """
    from olympia import amo
    from olympia.addons.models import AddonApprovalsCounter

    addon = version.addon
    channel_str = amo.CHANNEL_CHOICES_API[version.channel]

    # Authors (all listed; fall back to any author for unlisted-only addons)
    authors = list(addon.listed_authors)
    if not authors:
        authors = list(addon.authors.order_by('addonuser__position'))
    authors_str = ', '.join(f'{a.name} &lt;{a.email}&gt;' for a in authors) or 'Unknown'

    # Flags: NHR reasons + source-code flag
    flags = [
        nhr.get_reason_display()
        for nhr in version.needshumanreview_set.filter(is_active=True)
    ]
    if version.source:
        flags.append('Source code provided')
    flags_block = '\n'.join(f'* {f}' for f in flags) if flags else '_None_'

    # Stats
    adu = f'{addon.average_daily_users:,}' if addon.average_daily_users else 'N/A'
    weekly_dl = f'{addon.weekly_downloads:,}' if addon.weekly_downloads else 'N/A'
    rating = (
        f'{addon.average_rating:.1f}/5 ({addon.total_ratings} ratings)'
        if addon.average_rating
        else 'N/A'
    )

    # Approval history
    try:
        approvals = AddonApprovalsCounter.objects.get(addon=addon)
        last_human_review = (
            approvals.last_human_review.strftime('%Y-%m-%d')
            if approvals.last_human_review
            else 'Never'
        )
        human_approvals = approvals.counter
    except AddonApprovalsCounter.DoesNotExist:
        last_human_review = 'Never'
        human_approvals = 0

    due_date_str = (
        version.due_date.strftime('%Y-%m-%d %H:%M UTC')
        if version.due_date
        else 'Not set'
    )

    review_url = absolutify(
        reverse(
            'reviewers.review',
            kwargs={'addon_id': addon.pk, 'channel': channel_str},
            add_prefix=False,
        )
    )

    addon_type = amo.ADDON_TYPE_CHOICES_API.get(addon.type, str(addon.type))

    body = f"""\
## Add-on

**Name:** {addon.name}
**GUID:** `{addon.guid}`
**AMO ID:** {addon.pk}
**Type:** {addon_type}
**Status:** {addon.get_status_display()}

## Version

**Version:** {version.version}
**Channel:** {channel_str}
**Submitted:** {version.created.strftime('%Y-%m-%d')}
**Due date:** {due_date_str}
**Authors:** {authors_str}

## Flags

{flags_block}

## Stats

**ADU:** {adu}
**Weekly downloads:** {weekly_dl}
**Rating:** {rating}
**Last human review:** {last_human_review}
**Human approvals:** {human_approvals}"""

    if version.approval_notes:
        body += f'\n\n## Notes for reviewers\n\n{version.approval_notes}'

    if version.release_notes:
        body += f'\n\n## Release notes\n\n{version.release_notes}'

    body += f'\n\n---\n[Open in review tool]({review_url})'

    return body


def build_ticket_custom_fields(version):
    """Return the list of custom field dicts for a new review ticket."""
    from olympia import amo

    fields = []

    if settings.ZENDESK_FIELD_ID_ADDON_TYPE:
        addon_type_value = amo.ADDON_TYPE_CHOICES_API.get(version.addon.type)
        if addon_type_value:
            fields.append(
                {
                    'id': int(settings.ZENDESK_FIELD_ID_ADDON_TYPE),
                    'value': addon_type_value,
                }
            )

    if settings.ZENDESK_FIELD_ID_CHANNEL:
        fields.append(
            {
                'id': int(settings.ZENDESK_FIELD_ID_CHANNEL),
                'value': amo.CHANNEL_CHOICES_API[version.channel],
            }
        )

    if settings.ZENDESK_FIELD_ID_PROMOTED_GROUP:
        # An addon is typically in one active promoted group at a time.
        # We take the first one; if there is none the field is left unset.
        group = version.addon.promoted_groups(currently_approved=False).first()
        if group is not None:
            fields.append(
                {
                    'id': int(settings.ZENDESK_FIELD_ID_PROMOTED_GROUP),
                    'value': group.api_name,
                }
            )

    return fields


def build_comment_body(log_entry):
    """Return a Markdown-formatted body for a review conversation comment.

    Used to mirror AMO review activity (decisions, replies) as private
    Zendesk comments so operators can follow the full conversation without
    opening AMO.
    """
    from olympia.constants.activity import LOG_BY_ID

    action = LOG_BY_ID.get(log_entry.action)
    action_label = str(action.short) if action else f'Action {log_entry.action}'
    author_name = log_entry.user.name
    comment_text = (log_entry.details or {}).get('comments', '')

    body = f'**{action_label}** by {author_name}'
    if comment_text:
        body += f'\n\n{comment_text}'
    return body


def get_addon_primary_author(addon):
    """Return the primary author UserProfile for an addon, or None."""
    listed = list(addon.listed_authors)
    if listed:
        return listed[0]
    return addon.authors.order_by('addonuser__position').first()


def build_ticket_requester(version):
    """Return the requester dict {"name": str, "email": str} for a new review ticket,
    or None if the addon has no authors.
    """
    author = get_addon_primary_author(version.addon)
    if author is None:
        return None
    return {'name': author.name, 'email': author.email}


def build_ticket_collaborators(version):
    """Return collaborator dicts for all addon authors except the primary requester."""
    primary = get_addon_primary_author(version.addon)
    listed = list(version.addon.listed_authors)
    authors = listed if listed else list(
        version.addon.authors.order_by('addonuser__position')
    )
    return [
        {'name': a.name, 'email': a.email}
        for a in authors
        if primary is None or a.pk != primary.pk
    ]
