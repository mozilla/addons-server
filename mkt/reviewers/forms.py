import datetime
import logging

from django import forms

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from addons.models import AddonDeviceType, Persona
from amo.utils import raise_required
from editors.forms import NonValidatingChoiceField, ReviewLogForm
from editors.models import CannedResponse, ReviewerScore, ThemeLock

import mkt.constants.reviewers as rvw
from mkt.api.forms import CustomNullBooleanSelect
from mkt.reviewers.utils import ReviewHelper
from mkt.search.forms import ApiSearchForm

from .tasks import approve_rereview, reject_rereview, send_mail


log = logging.getLogger('z.reviewers.forms')


# We set 'any' here since we need to default this field
# to PUBLIC if not specified for consumer pages.
STATUS_CHOICES = [('any', _lazy(u'Any Status'))]
for status in amo.WEBAPPS_UNLISTED_STATUSES + (amo.STATUS_PUBLIC,):
    STATUS_CHOICES.append((amo.STATUS_CHOICES_API[status],
                           amo.MKT_STATUS_CHOICES[status]))


class ReviewAppForm(happyforms.Form):

    comments = forms.CharField(widget=forms.Textarea(),
                               label=_lazy(u'Comments:'))
    canned_response = NonValidatingChoiceField(required=False)
    action = forms.ChoiceField(widget=forms.RadioSelect())
    device_types = forms.CharField(required=False,
                                   label=_lazy(u'Device Types:'))
    browsers = forms.CharField(required=False,
                               label=_lazy(u'Browsers:'))
    device_override = forms.TypedMultipleChoiceField(
        choices=[(k, v.name) for k, v in amo.DEVICE_TYPES.items()],
        coerce=int, label=_lazy(u'Device Type Override:'),
        widget=forms.CheckboxSelectMultiple, required=False)
    notify = forms.BooleanField(
        required=False, label=_lazy(u'Notify me the next time the manifest is '
                                    u'updated. (Subsequent updates will not '
                                    u'generate an email)'))

    def __init__(self, *args, **kw):
        self.helper = kw.pop('helper')
        self.type = kw.pop('type', amo.CANNED_RESPONSE_APP)
        super(ReviewAppForm, self).__init__(*args, **kw)

        # We're starting with an empty one, which will be hidden via CSS.
        canned_choices = [['', [('', _('Choose a canned response...'))]]]

        responses = CannedResponse.objects.filter(type=self.type)

        # Loop through the actions.
        for k, action in self.helper.actions.iteritems():
            action_choices = [[c.response, c.name] for c in responses
                              if c.sort_group and k in c.sort_group.split(',')]

            # Add the group of responses to the canned_choices array.
            if action_choices:
                canned_choices.append([action['label'], action_choices])

        # Now, add everything not in a group.
        for r in responses:
            if not r.sort_group:
                canned_choices.append([r.response, r.name])

        self.fields['canned_response'].choices = canned_choices
        self.fields['action'].choices = [(k, v['label']) for k, v
                                         in self.helper.actions.items()]
        device_types = AddonDeviceType.objects.filter(
            addon=self.helper.addon).values_list('device_type', flat=True)
        if device_types:
            self.initial['device_override'] = device_types

    def is_valid(self):
        result = super(ReviewAppForm, self).is_valid()
        if result:
            self.helper.set_data(self.cleaned_data)
        return result


def get_review_form(data, files, request=None, addon=None, version=None,
                    attachment_formset=None):
    helper = ReviewHelper(request=request, addon=addon, version=version,
                          attachment_formset=attachment_formset)
    return ReviewAppForm(data=data, files=files, helper=helper)


class ReviewAppLogForm(ReviewLogForm):

    def __init__(self, *args, **kwargs):
        super(ReviewAppLogForm, self).__init__(*args, **kwargs)
        self.fields['search'].widget.attrs = {
            # L10n: Descript of what can be searched for.
            'placeholder': _lazy(u'app, reviewer, or comment'),
            'size': 30}


class DeletedThemeLogForm(ReviewLogForm):

    def __init__(self, *args, **kwargs):
        super(DeletedThemeLogForm, self).__init__(*args, **kwargs)
        self.fields['search'].widget.attrs = {
            # L10n: Descript of what can be searched for.
            'placeholder': _lazy(u'theme name'),
            'size': 30}


class ThemeReviewForm(happyforms.Form):
    theme = forms.ModelChoiceField(queryset=Persona.objects.all(),
                                   widget=forms.HiddenInput())
    action = forms.TypedChoiceField(
        choices=rvw.REVIEW_ACTIONS.items(),
        widget=forms.HiddenInput(attrs={'class': 'action'}),
        coerce=int, empty_value=None
    )
    # Duplicate is the same as rejecting but has its own flow.
    reject_reason = forms.TypedChoiceField(
        choices=rvw.THEME_REJECT_REASONS.items() + [('duplicate', '')],
        widget=forms.HiddenInput(attrs={'class': 'reject-reason'}),
        required=False, coerce=int, empty_value=None)
    comment = forms.CharField(required=False,
        widget=forms.HiddenInput(attrs={'class': 'comment'}))

    def clean_theme(self):
        theme = self.cleaned_data['theme']
        try:
            ThemeLock.objects.get(theme=theme)
        except (ThemeLock.DoesNotExist):
            raise forms.ValidationError(
                _('Someone else is reviewing this theme.'))
        return theme

    def clean_reject_reason(self):
        reject_reason = self.cleaned_data.get('reject_reason', None)
        if (self.cleaned_data.get('action') == rvw.ACTION_REJECT
            and reject_reason is None):
            raise_required()
        return reject_reason

    def clean_comment(self):
        # Comment field needed for duplicate, flag, moreinfo, and other reject
        # reason.
        action = self.cleaned_data.get('action')
        reject_reason = self.cleaned_data.get('reject_reason')
        comment = self.cleaned_data.get('comment')
        if (not comment and (action == rvw.ACTION_FLAG or
                             action == rvw.ACTION_MOREINFO or
                             (action == rvw.ACTION_REJECT and
                              reject_reason == 0))):
            raise_required()
        return comment

    def save(self):
        action = self.cleaned_data['action']
        comment = self.cleaned_data.get('comment')
        reject_reason = self.cleaned_data.get('reject_reason')
        theme = self.cleaned_data['theme']

        is_rereview = (
            theme.rereviewqueuetheme_set.exists() and
            theme.addon.status not in (amo.STATUS_PENDING,
                                       amo.STATUS_REVIEW_PENDING))

        theme_lock = ThemeLock.objects.get(theme=self.cleaned_data['theme'])

        mail_and_log = True
        if action == rvw.ACTION_APPROVE:
            if is_rereview:
                approve_rereview(theme)
            theme.addon.update(status=amo.STATUS_PUBLIC)
            theme.approve = datetime.datetime.now()
            theme.save()

        elif action == rvw.ACTION_REJECT:
            if is_rereview:
                reject_rereview(theme)
            else:
                theme.addon.update(status=amo.STATUS_REJECTED)

        elif action == rvw.ACTION_DUPLICATE:
            if is_rereview:
                reject_rereview(theme)
            else:
                theme.addon.update(status=amo.STATUS_REJECTED)

        elif action == rvw.ACTION_FLAG:
            if is_rereview:
                mail_and_log = False
            else:
                theme.addon.update(status=amo.STATUS_REVIEW_PENDING)

        elif action == rvw.ACTION_MOREINFO:
            if not is_rereview:
                theme.addon.update(status=amo.STATUS_REVIEW_PENDING)

        if mail_and_log:
            send_mail(self.cleaned_data, theme_lock)

            # Log.
            amo.log(amo.LOG.THEME_REVIEW, theme.addon, details={
                    'theme': theme.addon.name.localized_string,
                    'action': action,
                    'reject_reason': reject_reason,
                    'comment': comment}, user=theme_lock.reviewer)
            log.info('%sTheme %s (%s) - %s' % (
                '[Rereview] ' if is_rereview else '', theme.addon.name,
                theme.id, action))

        score = 0
        if action not in [rvw.ACTION_MOREINFO, rvw.ACTION_FLAG]:
            score = ReviewerScore.award_points(theme_lock.reviewer, theme.addon,
                                               theme.addon.status)
        theme_lock.delete()

        return score


class ThemeSearchForm(forms.Form):
    q = forms.CharField(
        required=False, label=_lazy(u'Search'),
        widget=forms.TextInput(attrs={'autocomplete': 'off',
                                      'placeholder': _lazy(u'Search')}))
    queue_type = forms.CharField(required=False, widget=forms.HiddenInput())


class ApiReviewersSearchForm(ApiSearchForm):
    status = forms.ChoiceField(required=False, choices=STATUS_CHOICES,
                               label=_lazy(u'Status'))
    has_editor_comment = forms.NullBooleanField(
        required=False,
        label=_lazy(u'Has Editor Comment'),
        widget=CustomNullBooleanSelect)
    has_info_request = forms.NullBooleanField(
        required=False,
        label=_lazy(u'More Info Requested'),
        widget=CustomNullBooleanSelect)
    is_escalated = forms.NullBooleanField(
        required=False,
        label=_lazy(u'Escalated'),
        widget=CustomNullBooleanSelect)

    def __init__(self, *args, **kwargs):
        super(ApiReviewersSearchForm, self).__init__(*args, **kwargs)

        # Mobile form, to render, expects choices from the Django field.
        BOOL_CHOICES = ((u'', _lazy('Unknown')),
                        (u'true', _lazy('Yes')),
                        (u'false', _lazy('No')))
        for field_name, field in self.fields.iteritems():
            if isinstance(field, forms.NullBooleanField):
                self.fields[field_name].choices = BOOL_CHOICES

    def clean_status(self):
        status = self.cleaned_data['status']
        if status == 'any':
            return 'any'

        return amo.STATUS_CHOICES_API_LOOKUP.get(status, amo.STATUS_PENDING)


class ApproveRegionForm(happyforms.Form):
    """TODO: Use a DRF serializer."""
    approve = forms.BooleanField(required=False)

    def __init__(self, *args, **kw):
        self.app = kw.pop('app')
        self.region = kw.pop('region')
        super(ApproveRegionForm, self).__init__(*args, **kw)

    def save(self):
        approved = self.cleaned_data['approve']

        if approved:
            status = amo.STATUS_PUBLIC
            # Make it public in the previously excluded region.
            self.app.addonexcludedregion.filter(
                region=self.region.id).delete()
        else:
            status = amo.STATUS_REJECTED

        value, changed = self.app.geodata.set_status(
            self.region, status, save=True)

        if changed:
            self.app.save()
