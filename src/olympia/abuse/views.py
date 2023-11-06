import hashlib
import hmac
from datetime import datetime

from django import forms
from django.conf import settings
from django.core.exceptions import PermissionDenied
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
from olympia.abuse.forms import AbuseAppealEmailForm, AbuseAppealForm
from olympia.abuse.models import CinderReport
from olympia.abuse.serializers import (
    AddonAbuseReportSerializer,
    RatingAbuseReportSerializer,
    UserAbuseReportSerializer,
)
from olympia.abuse.tasks import appeal_to_cinder
from olympia.accounts.utils import redirect_for_login
from olympia.accounts.views import AccountViewSet
from olympia.addons.views import AddonViewSet
from olympia.api.throttling import GranularIPRateThrottle, GranularUserRateThrottle
from olympia.ratings.views import RatingViewSet

from .cinder import CinderEntity


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


class CinderInboundPermission:
    """Permit if the payload hash matches."""

    def has_permission(self, request, view):
        header = request.headers.get('X-Cinder-Signature', '')
        key = force_bytes(settings.CINDER_WEBHOOK_TOKEN)
        digest = hmac.new(key, msg=request.body, digestmod=hashlib.sha256).hexdigest()
        return hmac.compare_digest(header, digest)


def process_datestamp(date_string):
    try:
        return datetime.fromisoformat(date_string.replace(' ', ''))
    except ValueError:
        log.warn('Invalid timestamp from cinder webhook %s', date_string)
        return datetime.now()


@api_view(['POST'])
@authentication_classes(())
@permission_classes((CinderInboundPermission,))
def cinder_webhook(request):
    if request.data.get('event') == 'decision.created' and (
        payload := request.data.get('payload', {})
    ):
        source = payload.get('source', {})
        job = source.get('job', {})
        if (queue_name := job.get('queue', {}).get('slug')) == CinderEntity.QUEUE:
            log.info('Valid Payload from AMO queue: %s', payload)
            job_id = job.get('id', '')
            decision_id = source.get('decision', {}).get('id')
            actions = payload.get('enforcement_actions')
            try:
                cinder_report = CinderReport.objects.get(job_id=job_id)
                cinder_report.process_decision(
                    decision_id=decision_id,
                    decision_date=process_datestamp(payload.get('timestamp')),
                    decision_actions=actions,
                )
            except CinderReport.DoesNotExist:
                log.debug('CinderReport instance not found for job id %s', job_id)
        else:
            log.info('Payload from other queue: %s', queue_name)
    else:
        log.info(
            'Non-decision payload received: %s',
            str(request.data)[:255],
        )

    return Response(data={'amo-received': True}, status=status.HTTP_201_CREATED)


def appeal(request, *, decision_id, **kwargs):
    cinder_report = get_object_or_404(
        CinderReport.objects.exclude(
            decision_action=CinderReport.DECISION_ACTIONS.NO_DECISION
        ),
        decision_id=decision_id,
    )
    abuse_report = cinder_report.abuse_report
    context_data = {
        'decision_id': decision_id,
    }
    post_data = request.POST if request.method == 'POST' else None
    valid_user_or_email_provided = False
    appeal_email_form = None
    decision = cinder_report.decision_action
    if decision in (
        CinderReport.DECISION_ACTIONS.AMO_APPROVE,
        CinderReport.DECISION_ACTIONS.AMO_BAN_USER,
    ):
        # Only person would should be appealing an approval is the reporter.
        if (
            decision == CinderReport.DECISION_ACTIONS.AMO_APPROVE
            and abuse_report.reporter
        ):
            # Authenticated reporter is the easy case, they should just be
            # authenticated with the right account.
            if not request.user.is_authenticated:
                return redirect_for_login(request)
            valid_user_or_email_provided = request.user == abuse_report.reporter
        elif (
            decision == CinderReport.DECISION_ACTIONS.AMO_BAN_USER
            or abuse_report.reporter_email
        ):
            # Anonymous reporter appealing or banned user appealing is tricky,
            # we need the email to be submitted via POST to match. If there was
            # no POST, then we show a form for it instead of showing the appeal
            # form. We do the same for ban appeals, since the user would no
            # longer be able to log in.
            expected_email = (
                abuse_report.user.email
                if decision == CinderReport.DECISION_ACTIONS.AMO_BAN_USER
                else abuse_report.reporter_email
            )
            appeal_email_form = AbuseAppealEmailForm(
                post_data, expected_email=expected_email
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
        if hasattr(abuse_report.target, 'authors'):
            allowed_users = abuse_report.target.authors.all()
        elif hasattr(abuse_report.target, 'author'):
            allowed_users = [abuse_report.target.author]
        elif hasattr(abuse_report.target, 'user'):
            allowed_users = [abuse_report.target.user]
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
        if cinder_report.can_be_appealed():
            appeal_form = AbuseAppealForm(post_data)
            if appeal_form.is_bound and appeal_form.is_valid():
                appeal_to_cinder.delay(
                    decision_id=decision_id,
                    appeal_text=appeal_form.cleaned_data['reason'],
                    user_id=request.user.pk,
                )
                context_data['appeal_processed'] = True
            context_data['appeal_form'] = appeal_form
        else:
            # We can't appeal this, remove email form if it was there (which at
            # this point should only contain the hidden email input) if the
            # report can't be appealed. No form should be left on the page.
            context_data.pop('appeal_email_form', None)

    return TemplateResponse(request, 'abuse/appeal.html', context=context_data)
