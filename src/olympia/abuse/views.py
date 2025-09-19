import hashlib
import hmac

from django import forms
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.utils.encoding import force_bytes

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.mixins import CreateModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

import olympia.core.logger
from olympia.abuse.tasks import appeal_to_cinder
from olympia.accounts.utils import redirect_for_login
from olympia.accounts.views import AccountViewSet
from olympia.addons.views import AddonViewSet
from olympia.api.throttling import GranularIPRateThrottle, GranularUserRateThrottle
from olympia.bandwagon.views import CollectionViewSet
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.core import set_user
from olympia.ratings.views import RatingViewSet
from olympia.users.models import UserProfile

from .actions import CONTENT_ACTION_FROM_DECISION_ACTION
from .cinder import CinderAddon
from .forms import AbuseAppealEmailForm, AbuseAppealForm
from .models import AbuseReport, CinderJob, ContentDecision
from .serializers import (
    AddonAbuseReportSerializer,
    CollectionAbuseReportSerializer,
    RatingAbuseReportSerializer,
    UserAbuseReportSerializer,
)


log = olympia.core.logger.getLogger('z.abuse')


class AbuseUserThrottle(GranularUserRateThrottle):
    rate = '20/day'
    scope = 'user_abuse'


class AbuseIPThrottle(GranularIPRateThrottle):
    rate = '20/day'
    scope = 'ip_abuse'


class AbuseTargetMixin:
    target_viewset_class = None  # Implement in child classes
    target_viewset_action = None  # Implement in child classes or leave None
    target_parameter_name = None  # Implement in child classes (must match serializer)

    def get_target_viewset(self):
        if hasattr(self, 'target_viewset'):
            return self.target_viewset

        if 'target_pk' not in self.kwargs:
            self.kwargs['target_pk'] = self.request.data.get(
                self.target_parameter_name
            ) or self.request.GET.get(self.target_parameter_name)

        self.target_viewset = self.target_viewset_class(
            request=self.request,
            permission_classes=[],
            kwargs={'pk': str(self.kwargs['target_pk'])},
            action=self.target_viewset_action,
        )
        return self.target_viewset

    # This method is used by the serializer.
    def get_target_object(self):
        if hasattr(self, 'target_object'):
            return self.target_object

        self.target_object = self.get_target_viewset().get_object()
        return self.target_object


class AddonAbuseViewSet(AbuseTargetMixin, CreateModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = AddonAbuseReportSerializer
    throttle_classes = (AbuseUserThrottle, AbuseIPThrottle)
    target_viewset_class = AddonViewSet
    target_viewset_action = 'retrieve_from_related'
    target_parameter_name = 'addon'

    def get_target_object(self):
        super().get_target_object()
        # It's possible to submit reports against non-public add-ons via guid,
        # but we can't reveal their slug/pk and can't accept their slug/pk as
        # input either. We raise a 404 if get_target_object() is called for a
        # non-public add-on: the view avoids calling it when a guid is passed
        # (see get_guid()) and the serializer will handle the Http404 when
        # returning the internal value (see get_addon() in serializer).
        if self.target_object and not self.target_object.is_public():
            raise Http404
        return self.target_object

    def get_guid(self):
        """
        Return the guid corresponding to the add-on the report is being made
        against.

        If `addon` in the POST/GET data looks like a guid, use that directly
        without looking in the database, but if not, consider it's a slug or pk
        belonging to a public add-on.

        Can raise Http404 if the `addon` parameter in POST/GET data doesn't
        look like a guid and there is no public add-on with a matching slug or
        pk.
        """
        if (
            self.get_target_viewset().get_lookup_field(self.kwargs['target_pk'])
            == 'guid'
        ):
            guid = self.kwargs['target_pk']
        else:
            # At this point the parameter is a slug or pk. For backwards-compatibility
            # we accept that, but ultimately record only the guid.
            self.get_target_object()
            if self.target_object:
                guid = self.target_object.guid
        return guid


class UserAbuseViewSet(AbuseTargetMixin, CreateModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = UserAbuseReportSerializer
    throttle_classes = (AbuseUserThrottle, AbuseIPThrottle)
    target_viewset_class = AccountViewSet
    target_parameter_name = 'user'


class RatingAbuseViewSet(AbuseTargetMixin, CreateModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = RatingAbuseReportSerializer
    throttle_classes = (AbuseUserThrottle, AbuseIPThrottle)
    target_viewset_class = RatingViewSet
    target_parameter_name = 'rating'


class CollectionAbuseViewSet(AbuseTargetMixin, CreateModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = CollectionAbuseReportSerializer
    throttle_classes = (AbuseUserThrottle, AbuseIPThrottle)
    target_viewset_class = CollectionViewSet
    target_parameter_name = 'collection'
    target_viewset_action = 'retrieve_from_pk'


class CinderInboundPermission:
    """Permit if the payload hash matches."""

    def has_permission(self, request, view):
        header = request.headers.get('X-Cinder-Signature', '')
        key = force_bytes(settings.CINDER_WEBHOOK_TOKEN)
        digest = hmac.new(key, msg=request.body, digestmod=hashlib.sha256).hexdigest()
        return hmac.compare_digest(header, digest)


class CinderWebhookError(ValidationError):
    """Validation error from Cinder webhook payload."""

    reportable = True  # True == should raise as 400 in response


class CinderWebhookIgnoredError(CinderWebhookError):
    """Not an error, we're just ignoring the decision because we already took action, or
    its for an entity we don't need to track."""

    reportable = False


class CinderWebhookMissingIdError(CinderWebhookError):
    """Potentially known error - for prod we want to fail as all ids should be known.
    For other envs ignore because we reuse Cinder stage."""

    @property
    def reportable(self):
        return settings.CINDER_UNIQUE_IDS


def filter_enforcement_actions(enforcement_actions, cinder_job):
    target = cinder_job.target
    if not target:
        return []
    return [
        action.value
        for action_slug in enforcement_actions
        if DECISION_ACTIONS.has_api_value(action_slug)
        and (action := DECISION_ACTIONS.for_api_value(action_slug))
        and target.__class__
        in CONTENT_ACTION_FROM_DECISION_ACTION[action.value].valid_targets
    ]


def process_webhook_payload_decision(payload):
    source = payload.get('source', {})
    log.info('Valid Payload from AMO queue: %s', payload)
    if source.get('decision', {}).get('type') == 'api_decision':
        log.debug('Cinder webhook decision for api decision skipped.')
        raise CinderWebhookIgnoredError('Decision already handled via reviewer tools')
    elif job_id := source.get('job', {}).get('id'):
        try:
            cinder_job = CinderJob.objects.get(job_id=job_id)
        except CinderJob.DoesNotExist as exc:
            log.debug('CinderJob instance not found for job id %s', job_id)
            raise CinderWebhookMissingIdError('No matching job id found') from exc
        queue_slug = source.get('job', {}).get('queue', {}).get('slug')
    elif prev_decision_id := payload.get('previous_decision', {}).get('id'):
        try:
            prev_decision = ContentDecision.objects.get(cinder_id=prev_decision_id)
        except ContentDecision.DoesNotExist as exc:
            log.debug('ContentDecision instance not found for id %s', prev_decision_id)
            raise CinderWebhookMissingIdError('No matching decision id found') from exc

        cinder_job = prev_decision.cinder_job
        if not cinder_job:
            log.debug('No job for ContentDecision with id %s', prev_decision_id)
            raise CinderWebhookMissingIdError('No matching job found for decision id')
        queue_slug = prev_decision.from_job_queue
    else:
        # We may support this one day, but we currently don't support this
        log.debug('Cinder webhook decision for cinder proactive decision skipped.')
        raise CinderWebhookError('Unsupported Manual decision')

    enforcement_actions = filter_enforcement_actions(
        payload.get('enforcement_actions') or [],
        cinder_job,
    )
    policy_ids = [policy['id'] for policy in payload.get('policies', [])]

    if len(enforcement_actions) != 1:
        reason = (
            'more than one supported enforcement_actions'
            if enforcement_actions
            else 'no supported enforcement_actions'
        )
        log.exception(
            f'Cinder webhook request failed: {reason} [%s]',
            payload.get('enforcement_actions'),
        )
        raise CinderWebhookError(f'Payload invalid: {reason}')

    created = cinder_job.process_decision(
        decision_cinder_id=source.get('decision', {}).get('id'),
        decision_action=enforcement_actions[0],
        decision_notes=payload.get('notes') or '',
        policy_ids=policy_ids,
        job_queue=queue_slug,
    )
    if not created:
        raise CinderWebhookIgnoredError('Decision already exists')


def process_webhook_payload_job_actioned(payload):
    if (action := payload.get('action')) != 'escalated':
        log.debug('Cinder webhook action was invalid (not "escalated")')
        raise CinderWebhookError(f'Unsupported action ({action}) for job.actioned')
    job = payload.get('job', {})
    entity = job.get('entity', {}).get('entity_schema')
    if entity != CinderAddon.type:
        log.debug('Cinder webhook entity_schema was not %s', CinderAddon.type)
        raise CinderWebhookIgnoredError(
            f'Unsupported entity_schema ({entity}) for job.actioned'
        )
    job_id = job.get('id', '')

    try:
        cinder_job = CinderJob.objects.get(job_id=job_id)
    except CinderJob.DoesNotExist as exc:
        log.debug('CinderJob instance not found for job id %s', job_id)
        raise CinderWebhookMissingIdError('No matching job id found') from exc

    new_queue = payload.get('job', {}).get('queue', {}).get('slug')
    notes = payload.get('notes', '')
    cinder_job.process_queue_move(new_queue=new_queue, notes=notes)


@api_view(['POST'])
@authentication_classes(())
@permission_classes((CinderInboundPermission,))
def cinder_webhook(request):
    # Normally setting the user would be done in the authentication class but
    # we don't have one here.
    set_user(UserProfile.objects.get(pk=settings.TASK_USER_ID))

    try:
        if (
            not (payload := request.data.get('payload', {}))
            or not isinstance(payload, dict)
            or not payload
        ):
            log.info('No payload dict received: %s', str(request.data)[:255])
            raise CinderWebhookError('No payload dict')
        match event := request.data.get('event'):
            case 'decision.created':
                process_webhook_payload_decision(payload)
            case 'job.actioned':
                process_webhook_payload_job_actioned(payload)
            case _:
                log.info('Unsupported payload received: %s', str(request.data)[:255])
                raise CinderWebhookError(f'{event} is not a event we support')

    except CinderWebhookError as exc:
        return Response(
            data={
                'amo': {
                    'received': True,
                    'handled': False,
                    'not_handled_reason': exc.message,
                }
            },
            # We differentiate errors we want exposed in Cinder's logs, and known cases
            # where we can safely ignore the error.
            status=(
                status.HTTP_400_BAD_REQUEST if exc.reportable else status.HTTP_200_OK
            ),
        )
    return Response(
        data={'amo': {'received': True, 'handled': True}},
        status=status.HTTP_201_CREATED,
    )


def appeal(request, *, abuse_report_id, decision_cinder_id, **kwargs):
    appealable_decisions = tuple(DECISION_ACTIONS.APPEALABLE_BY_AUTHOR.values) + tuple(
        DECISION_ACTIONS.APPEALABLE_BY_REPORTER.values
    )
    cinder_decision = get_object_or_404(
        ContentDecision.objects.filter(action__in=appealable_decisions),
        cinder_id=decision_cinder_id,
    )

    if abuse_report_id:
        abuse_report = get_object_or_404(
            AbuseReport.objects.filter(cinder_job__isnull=False),
            id=abuse_report_id,
            cinder_job=cinder_decision.cinder_job,
        )
    else:
        abuse_report = None
    # Reporter appeal: we need an abuse report.
    if (
        abuse_report is None
        and cinder_decision.action in DECISION_ACTIONS.APPEALABLE_BY_REPORTER
    ):
        raise Http404

    target = cinder_decision.target
    context_data = {
        'decision_cinder_id': decision_cinder_id,
    }
    post_data = request.POST if request.method == 'POST' else None
    valid_user_or_email_provided = False
    appeal_email_form = None
    if cinder_decision.action in DECISION_ACTIONS.APPEALABLE_BY_REPORTER or (
        cinder_decision.action == DECISION_ACTIONS.AMO_BAN_USER
    ):
        # Only person would should be appealing an approval is the reporter.
        if (
            cinder_decision.action in DECISION_ACTIONS.APPEALABLE_BY_REPORTER
            and abuse_report
            and abuse_report.reporter
        ):
            # Authenticated reporter is the easy case, they should just be
            # authenticated with the right account.
            if not request.user.is_authenticated:
                return redirect_for_login(request)
            valid_user_or_email_provided = request.user == abuse_report.reporter
        elif cinder_decision.action == DECISION_ACTIONS.AMO_BAN_USER or (
            abuse_report and abuse_report.reporter_email
        ):
            # Anonymous reporter appealing or banned user appealing is tricky,
            # we need the email to be submitted via POST to match. If there was
            # no POST, then we show a form for it instead of showing the appeal
            # form. We do the same for ban appeals, since the user would no
            # longer be able to log in.
            expected_email = (
                target.email
                if cinder_decision.action == DECISION_ACTIONS.AMO_BAN_USER
                else abuse_report.reporter_email
            )
            appeal_email_form = AbuseAppealEmailForm(
                post_data, expected_email=expected_email, request=request
            )
            if appeal_email_form.is_bound and appeal_email_form.is_valid():
                valid_user_or_email_provided = True
                # We'll be re-using the form, but the user shouldn't change
                # the email (that would prevent submission, it would no
                # longer be valid), so make the input hidden.
                appeal_email_form.fields['email'].widget = forms.HiddenInput()
            context_data['appeal_email_form'] = appeal_email_form
    else:
        # Only person would should be appealing anything else than an approval
        # is the author of the content.
        if not request.user.is_authenticated:
            return redirect_for_login(request)

        allowed_users = []
        if hasattr(target, 'authors'):
            allowed_users = target.authors.all()
        elif hasattr(target, 'author'):
            allowed_users = [target.author]
        elif hasattr(target, 'user'):
            allowed_users = [target.user]
        valid_user_or_email_provided = request.user in allowed_users

    if not valid_user_or_email_provided and not appeal_email_form:
        # At this point we should either have a valid user/email provided, or
        # we are just showing the email form. Anything else should result in a
        # 403.
        raise PermissionDenied

    if valid_user_or_email_provided:
        # After this point, the user is either authenticated or has entered the
        # right email address, we can start testing whether or not they can
        # actually appeal, and show the form if they indeed can.
        is_reporter = cinder_decision.action in DECISION_ACTIONS.APPEALABLE_BY_REPORTER
        if cinder_decision.can_be_appealed(
            is_reporter=is_reporter, abuse_report=abuse_report
        ):
            appeal_form = AbuseAppealForm(post_data, request=request)
            if appeal_form.is_bound and appeal_form.is_valid():
                appeal_to_cinder.delay(
                    decision_cinder_id=cinder_decision.cinder_id,
                    abuse_report_id=abuse_report.id if abuse_report else None,
                    appeal_text=appeal_form.cleaned_data['reason'],
                    user_id=request.user.pk,
                    is_reporter=is_reporter,
                )
                context_data['appeal_processed'] = True
            context_data['appeal_form'] = appeal_form
        else:
            # We can't appeal this, remove email form if it was there (which at
            # this point should only contain the hidden email input) if the
            # report can't be appealed. No form should be left on the page.
            context_data.pop('appeal_email_form', None)
            if hasattr(cinder_decision, 'overridden_by'):
                # The reason we can't appeal this is that the decision has already been
                # overriden by a new decision. We want a specific error message in this
                # case.
                context_data['appealed_decision_overridden'] = True
            elif (
                is_reporter
                and not hasattr(abuse_report, 'cinderappeal')
                and cinder_decision.appealed_decision_already_made()
            ):
                # The reason we can't appeal this is that there was already an
                # appeal made for which we have a decision. We want a specific
                # error message in this case.
                context_data['appealed_decision_already_made'] = True
                context_data['appealed_decision_affirmed'] = (
                    cinder_decision.appeal_job.final_decision.action
                    == cinder_decision.action
                )

    return TemplateResponse(request, 'abuse/appeal.html', context=context_data)
