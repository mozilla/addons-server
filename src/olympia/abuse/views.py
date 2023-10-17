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
    UserAbuseReportSerializer,
)
from olympia.abuse.tasks import appeal_to_cinder
from olympia.accounts.utils import redirect_for_login
from olympia.accounts.views import AccountViewSet
from olympia.addons.views import AddonViewSet
from olympia.api.throttling import GranularIPRateThrottle, GranularUserRateThrottle

from .cinder import CinderEntity


log = olympia.core.logger.getLogger('z.abuse')


class AbuseUserThrottle(GranularUserRateThrottle):
    rate = '20/day'
    scope = 'user_abuse'


class AbuseIPThrottle(GranularIPRateThrottle):
    rate = '20/day'
    scope = 'ip_abuse'


class AddonAbuseViewSet(CreateModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = AddonAbuseReportSerializer
    throttle_classes = (AbuseUserThrottle, AbuseIPThrottle)

    def get_addon_viewset(self):
        if hasattr(self, 'addon_viewset'):
            return self.addon_viewset

        if 'addon_pk' not in self.kwargs:
            self.kwargs['addon_pk'] = self.request.data.get(
                'addon'
            ) or self.request.GET.get('addon')
        self.addon_viewset = AddonViewSet(
            request=self.request,
            permission_classes=[],
            kwargs={'pk': self.kwargs['addon_pk']},
            action='retrieve_from_related',
        )
        return self.addon_viewset

    def get_addon_object(self):
        if hasattr(self, 'addon_object'):
            return self.addon_object

        self.addon_object = self.get_addon_viewset().get_object()
        if self.addon_object and not self.addon_object.is_public():
            raise Http404
        return self.addon_object

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
        if self.get_addon_viewset().get_lookup_field(self.kwargs['addon_pk']) == 'guid':
            guid = self.kwargs['addon_pk']
        else:
            # At this point the parameter is a slug or pk. For backwards-compatibility
            # we accept that, but ultimately record only the guid.
            self.get_addon_object()
            if self.addon_object:
                guid = self.addon_object.guid
        return guid


class UserAbuseViewSet(CreateModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = UserAbuseReportSerializer
    throttle_classes = (AbuseUserThrottle, AbuseIPThrottle)

    def get_user_object(self):
        if hasattr(self, 'user_object'):
            return self.user_object

        if 'user_pk' not in self.kwargs:
            self.kwargs['user_pk'] = self.request.data.get(
                'user'
            ) or self.request.GET.get('user')

        return AccountViewSet(
            request=self.request,
            permission_classes=[],
            kwargs={'pk': self.kwargs['user_pk']},
        ).get_object()


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
        # FIXME: when we implement collections in abuse reports
        # elif hasattr(abuse_report.target, 'author'):
        #     allowed_users = [abuse_report.target.author]
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
